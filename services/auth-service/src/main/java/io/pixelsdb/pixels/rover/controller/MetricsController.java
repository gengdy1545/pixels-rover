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

import io.prometheus.client.CollectorRegistry;
import io.prometheus.client.exporter.common.TextFormat;
import io.prometheus.client.hotspot.DefaultExports;
import jakarta.annotation.PostConstruct;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.io.StringWriter;

/**
 * Prometheus text-format metrics endpoint for auth-service.
 *
 * <p>Stage A exposure (see {@code docs/runbooks/observability-roadmap.md §2.1}):
 * only the default JVM / process / GC collectors registered by
 * {@link DefaultExports#initialize()} are exposed. No business counters
 * ({@code auth_login_failures_total}, {@code auth_refresh_failures_total},
 * {@code auth_introspection_failures_total}, {@code request_id_missing_total},
 * ...) are registered yet; their naming + labels are parked in §2.1 of the
 * roadmap and will be materialized together with the metrics-pipeline
 * decision at stage B.</p>
 *
 * <p>Why the endpoint exists even before a scraper is deployed: the
 * observability roadmap's §2 rule 5 requires {@code /metrics} to return
 * 200 + correct Prometheus text format at all times, so a future scraper
 * can attach without a coordinated dev-side scramble.</p>
 *
 * <p>External exposure: {@code apisix.yaml.template} does NOT publish
 * {@code /metrics} under any public route, so access is blocked at the
 * gateway boundary. The Spring Security {@code publicAndUserChain} adds
 * the path to {@code permitAll()} only so that in-cluster scrapes (e.g.
 * from a sidecar or an internal Prometheus) can reach it without
 * {@code X-Auth-*} injection.</p>
 */
@RestController
public class MetricsController
{
    /**
     * Registers JVM / process / GC collectors against the default registry.
     * Idempotent: re-registration is guarded internally by
     * {@link DefaultExports#register(CollectorRegistry)}, so @PostConstruct
     * running under a single ApplicationContext is safe even when Spring
     * DevTools triggers a restart.
     */
    @PostConstruct
    public void init()
    {
        DefaultExports.initialize();
    }

    @GetMapping("/metrics")
    public ResponseEntity<String> metrics() throws IOException
    {
        StringWriter writer = new StringWriter();
        TextFormat.write004(writer, CollectorRegistry.defaultRegistry.metricFamilySamples());
        return ResponseEntity.ok()
                .header("Content-Type", TextFormat.CONTENT_TYPE_004)
                .contentType(MediaType.parseMediaType(TextFormat.CONTENT_TYPE_004))
                .body(writer.toString());
    }
}
