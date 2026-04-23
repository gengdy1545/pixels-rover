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
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/**
 * Consumes the inbound {@code X-Request-Id} header for logging and body-envelope
 * propagation, generating a UUID fallback when the header is absent.
 *
 * <p><b>Contract (gateway.md §7.5 / §7.6 + backend.md §5):</b> the gateway's
 * global {@code response-rewrite} / {@code request-id} plugin is the <i>sole</i>
 * writer of the outbound {@code X-Request-Id} response header. Business services
 * MUST NOT set this header themselves — doing so creates two writers, which
 * breaks the "single writer" invariant that {@code scripts/check-contracts.py}
 * enforces and lets request-id values drift between log line and response header
 * during middleware rewrites.</p>
 *
 * <p>The fallback id is reported via the body envelope's {@code requestId} field
 * (populated from {@link RequestIdContext}) — see {@code ApiResponse} — so
 * downstream consumers always have a stable correlation handle even in the
 * "no inbound header" path.</p>
 */
@Component
public class RequestIdFilter extends OncePerRequestFilter
{
    public static final String REQUEST_ID_HEADER = "X-Request-Id";
    private static final String MDC_KEY = "requestId";

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException
    {
        String requestId = request.getHeader(REQUEST_ID_HEADER);
        if (!StringUtils.hasText(requestId))
        {
            requestId = UUID.randomUUID().toString();
        }

        RequestIdContext.set(requestId);
        MDC.put(MDC_KEY, requestId);

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
}
