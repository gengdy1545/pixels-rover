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
package io.pixelsdb.pixels.rover.config;

import io.pixelsdb.pixels.rover.config.common.RequestIdContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.security.SecureRandom;
import java.util.HexFormat;

/**
 * Consumes the inbound {@code X-Request-Id} header for logging and body-envelope
 * propagation.
 *
 * <p><b>Contract (gateway.md §7.5 / §7.6 + backend.md §5):</b> the gateway's
 * global {@code response-rewrite} / {@code request-id} plugin is the <i>sole</i>
 * writer of the outbound {@code X-Request-Id} response header. Business services
 * MUST NOT set this header themselves — doing so creates two writers, which
 * breaks the "single writer" invariant that {@code scripts/check-contracts.py}
 * enforces and lets request-id values drift between log line and response header
 * during middleware rewrites.</p>
 *
 * <p><b>Fallback rule (backend.md §5):</b> when the inbound header is absent
 * this filter performs exactly three actions:</p>
 * <ol>
 *   <li>emit a single {@code request_id_missing=true} warning carrying the
 *       triggering route + method so the upstream gateway misconfig is
 *       investigable from the log aggregator alone;</li>
 *   <li>use the literal {@code missing-<8 hex>} as the local request id in
 *       both MDC and the body envelope's {@code requestId} field so the
 *       single-event log line can still be aggregated — the {@code missing-}
 *       prefix keeps the fallback visually distinct from a real gateway id;</li>
 *   <li>never write the fallback value back onto the response header; see
 *       the single-writer invariant above.</li>
 * </ol>
 */
@Component
public class RequestIdFilter extends OncePerRequestFilter
{
    public static final String REQUEST_ID_HEADER = "X-Request-Id";
    public static final String FALLBACK_PREFIX = "missing-";
    private static final String MDC_KEY = "requestId";

    /** 4 bytes = 8 hex chars per backend.md §5 fallback shape. */
    private static final int FALLBACK_RAND_BYTES = 4;

    private static final Logger LOGGER = LoggerFactory.getLogger(RequestIdFilter.class);

    /**
     * {@link SecureRandom} is thread-safe per the JDK spec; a single shared
     * instance avoids the (small but non-zero) per-request seeding cost of
     * creating a fresh one on every fallback path.
     */
    private static final SecureRandom RAND = new SecureRandom();

    private static final HexFormat HEX = HexFormat.of();

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException
    {
        String inbound = request.getHeader(REQUEST_ID_HEADER);
        String requestId;
        boolean isFallback;
        if (StringUtils.hasText(inbound))
        {
            requestId = inbound;
            isFallback = false;
        }
        else
        {
            requestId = generateFallbackRequestId();
            isFallback = true;
        }

        RequestIdContext.set(requestId);
        MDC.put(MDC_KEY, requestId);

        if (isFallback)
        {
            // backend.md §5 rule 1: exactly one warning per fallback request.
            LOGGER.warn("request_id_missing=true route={} method={} fallback={}",
                    request.getRequestURI(), request.getMethod(), requestId);
        }

        try
        {
            filterChain.doFilter(request, response);
        }
        finally
        {
            MDC.remove(MDC_KEY);
            MDC.remove("userId");
            RequestIdContext.clear();
        }
    }

    /**
     * Produces the {@code missing-<8 hex chars>} literal mandated by
     * {@code backend.md §5} rule 2. Package-private so that
     * {@code RequestIdFilterTest} can exercise the shape directly without
     * routing a full servlet request through the filter chain.
     */
    static String generateFallbackRequestId()
    {
        byte[] buf = new byte[FALLBACK_RAND_BYTES];
        RAND.nextBytes(buf);
        return FALLBACK_PREFIX + HEX.formatHex(buf);
    }
}
