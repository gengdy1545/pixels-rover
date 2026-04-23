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
package io.pixelsdb.pixels.rover.config.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.config.common.ErrorCategory;
import io.pixelsdb.pixels.rover.config.common.ErrorCodeName;
import io.pixelsdb.pixels.rover.constant.HttpStatus;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.util.AntPathMatcher;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Guards every {@code /api/internal/**} route with a shared-secret header check.
 *
 * <p>Contract comes from {@code backend.md §8.6}:</p>
 * <ul>
 *     <li>Scope is the whole {@code /api/internal/**} prefix, not any single URI — a future
 *         internal endpoint added without updating this filter must still be protected.</li>
 *     <li>Secret mismatch / missing header returns HTTP {@code 500} with
 *         {@code details.errorCode="INTERNAL_AUTH_FAILED"} and the unified envelope; 401/403
 *         are explicitly forbidden to avoid leaking probe-friendly signals.</li>
 * </ul>
 */
public class InternalAuthFilter extends OncePerRequestFilter
{
    public static final String INTERNAL_AUTH_HEADER = "X-Internal-Auth";
    public static final String INTERNAL_PATH_PATTERN = "/api/internal/**";

    private static final Logger log = LoggerFactory.getLogger(InternalAuthFilter.class);
    private static final AntPathMatcher MATCHER = new AntPathMatcher();
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final String sharedSecret;

    public InternalAuthFilter(String sharedSecret)
    {
        this.sharedSecret = sharedSecret;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request)
    {
        return !MATCHER.match(INTERNAL_PATH_PATTERN, request.getRequestURI());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException
    {
        String provided = request.getHeader(INTERNAL_AUTH_HEADER);
        if (!StringUtils.hasText(sharedSecret) || !sharedSecret.equals(provided))
        {
            String branch = provided == null || provided.isBlank() ? "missing" : "mismatch";
            log.error("Internal auth check failed: internal_call=true branch={} method={} uri={}",
                    branch, request.getMethod(), request.getRequestURI());
            writeInternalAuthFailed(response);
            return;
        }

        filterChain.doFilter(request, response);
    }

    private static void writeInternalAuthFailed(HttpServletResponse response) throws IOException
    {
        response.setStatus(HttpStatus.ERROR);
        response.setContentType("application/json;charset=UTF-8");
        ApiResponse<?> body = ApiResponse.error(
                HttpStatus.ERROR,
                "Internal authentication failed",
                ErrorCodeName.INTERNAL_AUTH_FAILED,
                ErrorCategory.INTERNAL);
        response.getWriter().write(OBJECT_MAPPER.writeValueAsString(body));
    }
}
