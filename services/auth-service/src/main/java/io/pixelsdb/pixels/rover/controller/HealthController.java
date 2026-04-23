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

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Process-level liveness endpoint for auth-service.
 * <p>
 * Contract (docs/development/backend.md §7.1): this endpoint MUST only
 * report "the JVM is up and able to respond to HTTP". It MUST NOT probe
 * the database, cache, or any external dependency — those belong to
 * {@link InternalReadyController} ({@code /internal/ready}).
 * <p>
 * Consumers: Docker {@code HEALTHCHECK}, Kubernetes {@code livenessProbe},
 * docker-compose {@code depends_on: condition: service_started}. A failure
 * here means the process is wedged and a restart may help; DB failures
 * are deliberately invisible to this endpoint because restarting auth-service
 * will not fix MySQL being down.
 *
 * @author pixels
 */
@RestController
public class HealthController
{
    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health()
    {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "UP");
        result.put("service", "auth-service");
        result.put("version", "0.1.0");
        return ResponseEntity.ok(result);
    }
}
