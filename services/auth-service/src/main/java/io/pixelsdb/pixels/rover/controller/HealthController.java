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

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.sql.DataSource;
import java.sql.Connection;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Health check endpoint for the auth service.
 * <p>
 * This endpoint is publicly accessible (no authentication required)
 * and is intended for use by container orchestration, load balancers,
 * and monitoring systems.
 *
 * @author pixels
 */
@RestController
public class HealthController
{
    private static final Logger log = LoggerFactory.getLogger(HealthController.class);

    private final DataSource dataSource;

    public HealthController(DataSource dataSource)
    {
        this.dataSource = dataSource;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health()
    {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("service", "auth-service");
        result.put("version", "0.1.0");

        Map<String, Object> checks = new LinkedHashMap<>();

        // Database connectivity check
        try (Connection conn = dataSource.getConnection())
        {
            boolean valid = conn.isValid(3);
            checks.put("database", Map.of("status", valid ? "UP" : "DOWN"));
        }
        catch (Exception e)
        {
            log.warn("Health check: database connection failed: {}", e.getMessage());
            checks.put("database", Map.of("status", "DOWN", "error", e.getMessage()));
        }

        result.put("checks", checks);

        boolean allUp = checks.values().stream()
                .allMatch(v -> v instanceof Map && "UP".equals(((Map<?, ?>) v).get("status")));
        result.put("status", allUp ? "UP" : "DOWN");

        int httpStatus = allUp ? 200 : 503;
        return ResponseEntity.status(httpStatus).body(result);
    }
}
