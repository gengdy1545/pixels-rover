/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package io.pixelsdb.pixels.rover.controller;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.sql.DataSource;
import java.sql.Connection;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Internal readiness endpoint for auth-service.
 * <p>
 * Contract (docs/development/backend.md §7.2):
 * <ul>
 *     <li>Reports "this service and its direct dependencies are ready to serve traffic".
 *     Probed dependencies: MySQL connectivity ({@code SELECT 1}) and Flyway
 *     migration head.</li>
 *     <li>Only consumed by the gateway via an {@code internal} location
 *     ({@code /__ready_probe/auth}). External callers MUST be blocked by
 *     gateway routing; nginx's {@code internal;} directive enforces this at
 *     the gateway layer so that no service-side secret is required here.</li>
 *     <li>Returns 503 + {@code SERVICE_NOT_READY} on any dependency failure;
 *     consumers (gateway-ready plugin) treat non-200 as not-ready. Dependency
 *     details live in {@code details.checks[*].status} without inventing a
 *     new errorCode per dependency.</li>
 *     <li>Failure here MUST NOT trigger container restart — it is not a
 *     liveness signal. That's what {@code /health} is for.</li>
 * </ul>
 *
 * Mapped under {@code /internal/*} to mirror the gateway-internal URL prefix
 * convention (see backend.md §8.6); gateway routing MUST NOT expose this
 * prefix externally.
 *
 * @author pixels
 */
@RestController
@RequestMapping("/internal")
public class InternalReadyController
{
    private static final Logger log = LoggerFactory.getLogger(InternalReadyController.class);

    private final DataSource dataSource;

    /**
     * Flyway bean auto-registered by Spring Boot's {@code FlywayAutoConfiguration}.
     * Optional because the bean is only present when {@code flyway-core} is on
     * the classpath, which it is in this module — but keeping {@code required=false}
     * guards against accidental classpath regression turning /internal/ready into
     * a startup crash instead of a 503.
     */
    private final Flyway flyway;

    public InternalReadyController(
            DataSource dataSource,
            @Autowired(required = false) Flyway flyway)
    {
        this.dataSource = dataSource;
        this.flyway = flyway;
    }

    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready()
    {
        Map<String, Object> checks = new LinkedHashMap<>();

        boolean dbUp = checkDatabase(checks);
        boolean migrationUp = checkMigration(checks);

        boolean allUp = dbUp && migrationUp;

        if (allUp)
        {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("code", 200);
            body.put("message", "ready");

            Map<String, Object> data = new LinkedHashMap<>();
            data.put("status", "UP");
            data.put("service", "auth-service");
            data.put("version", "0.1.0");
            data.put("checks", checks);
            body.put("data", data);
            return ResponseEntity.ok(body);
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", 503);
        body.put("message", "auth-service is not ready: one or more dependencies DOWN");

        Map<String, Object> details = new LinkedHashMap<>();
        details.put("errorCode", "SERVICE_NOT_READY");
        details.put("category", "UPSTREAM");
        details.put("checks", checks);
        body.put("details", details);
        return ResponseEntity.status(503).body(body);
    }

    private boolean checkDatabase(Map<String, Object> checks)
    {
        try (Connection conn = dataSource.getConnection())
        {
            boolean valid = conn.isValid(1);
            if (valid)
            {
                checks.put("database", Map.of("status", "UP"));
                return true;
            }
            checks.put("database", Map.of(
                    "status", "DOWN",
                    "error", "connection.isValid(1) returned false"));
            return false;
        }
        catch (Exception e)
        {
            log.warn("/internal/ready: database check failed: {}", e.getMessage());
            checks.put("database", Map.of(
                    "status", "DOWN",
                    "error", e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage())));
            return false;
        }
    }

    /**
     * Verify that Flyway has applied at least one migration and there is no
     * pending migration known to the classpath. Because Spring Boot runs
     * Flyway during {@code ApplicationContext} startup, a pending migration
     * at this point means "something went wrong during startup migration but
     * the app kept running" — an abnormal state worth surfacing as 503.
     */
    private boolean checkMigration(Map<String, Object> checks)
    {
        if (flyway == null)
        {
            checks.put("migrations", Map.of(
                    "status", "DOWN",
                    "error", "Flyway bean not present; classpath regression?"));
            return false;
        }

        try
        {
            MigrationInfo current = flyway.info().current();
            MigrationInfo[] pending = flyway.info().pending();

            if (current == null)
            {
                checks.put("migrations", Map.of(
                        "status", "DOWN",
                        "error", "no current migration applied (empty schema history)"));
                return false;
            }

            if (pending != null && pending.length > 0)
            {
                checks.put("migrations", Map.of(
                        "status", "DOWN",
                        "head", String.valueOf(current.getVersion()),
                        "pending", pending.length));
                return false;
            }

            checks.put("migrations", Map.of(
                    "status", "UP",
                    "head", String.valueOf(current.getVersion())));
            return true;
        }
        catch (Exception e)
        {
            log.warn("/internal/ready: Flyway info check failed: {}", e.getMessage());
            checks.put("migrations", Map.of(
                    "status", "DOWN",
                    "error", e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage())));
            return false;
        }
    }
}
