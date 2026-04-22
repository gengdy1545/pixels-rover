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
import io.pixelsdb.pixels.rover.config.common.ErrorCodeName;
import io.pixelsdb.pixels.rover.constant.HttpStatus;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.AntPathMatcher;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * Pre-validates {@code X-Auth-User-Id} for protected user-facing routes of auth-service.
 *
 * <p>Semantics come from {@code backend.md §3.3}: the "header missing" and "header present
 * but malformed" cases must map to the same branch — HTTP 500 +
 * {@code details.errorCode="GATEWAY_IDENTITY_MISSING"}. Letting individual controllers
 * enforce this would invite silent downgrades to 400-style domain errors.</p>
 *
 * <p>This filter is the dual of {@link InternalAuthFilter}: InternalAuthFilter guards the
 * {@code /api/internal/**} surface with a shared secret; this filter guards the user-facing
 * {@code /api/v1/auth/**} surface with gateway-injected identity.</p>
 *
 * <p>When the header is valid the filter also materializes a minimal Spring Security
 * {@link UsernamePasswordAuthenticationToken} so that {@code .anyRequest().authenticated()}
 * on the public-and-user chain is satisfied without any AuthN logic running locally; the
 * trust anchor is gateway's introspect — see {@code backend.md §3.4}.</p>
 */
public class IdentityHeaderValidationFilter extends OncePerRequestFilter
{
    public static final String USER_ID_HEADER = "X-Auth-User-Id";
    public static final String USER_EMAIL_HEADER = "X-Auth-User-Email";
    public static final String SESSION_ID_HEADER = "X-Auth-Session-Id";

    private static final Logger log = LoggerFactory.getLogger(IdentityHeaderValidationFilter.class);
    private static final AntPathMatcher MATCHER = new AntPathMatcher();
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    /**
     * Routes that require a valid gateway-injected identity.
     * Public entry points ({@code login} / {@code register} / {@code captcha} / {@code refresh})
     * and {@code /health} are intentionally excluded.
     */
    private static final List<String> PROTECTED_PATTERNS = Arrays.asList(
            "/api/v1/auth/me",
            "/api/v1/auth/user-info",
            "/api/v1/auth/logout",
            "/api/v1/auth/logout-all",
            "/api/v1/auth/sessions",
            "/api/v1/auth/sessions/**"
    );

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request)
    {
        String uri = request.getRequestURI();
        for (String pattern : PROTECTED_PATTERNS)
        {
            if (MATCHER.match(pattern, uri))
            {
                return false;
            }
        }
        return true;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException
    {
        String raw = request.getHeader(USER_ID_HEADER);
        Long userId = parseUserId(raw);
        if (userId == null)
        {
            String branch = raw == null ? "missing" : "malformed";
            log.error(
                    "Gateway identity header invalid: level=critical branch={} method={} uri={} host={} remoteAddr={} header='{}'",
                    branch,
                    request.getMethod(),
                    request.getRequestURI(),
                    request.getHeader("Host"),
                    resolveClientIp(request),
                    sanitize(raw)
            );
            writeIdentityMissingResponse(response);
            return;
        }

        String email = request.getHeader(USER_EMAIL_HEADER);
        String principalName = (email != null && !email.isBlank()) ? email : String.valueOf(userId);
        UsernamePasswordAuthenticationToken authentication =
                new UsernamePasswordAuthenticationToken(
                        principalName,
                        null,
                        Collections.singletonList(new SimpleGrantedAuthority("ROLE_USER")));
        SecurityContextHolder.getContext().setAuthentication(authentication);
        MDC.put("userId", String.valueOf(userId));
        try
        {
            chain.doFilter(request, response);
        }
        finally
        {
            MDC.remove("userId");
            SecurityContextHolder.clearContext();
        }
    }

    private static Long parseUserId(String raw)
    {
        if (raw == null)
        {
            return null;
        }
        String trimmed = raw.trim();
        if (trimmed.isEmpty())
        {
            return null;
        }
        try
        {
            long id = Long.parseLong(trimmed);
            return id > 0 ? id : null;
        }
        catch (NumberFormatException ex)
        {
            return null;
        }
    }

    private static void writeIdentityMissingResponse(HttpServletResponse response) throws IOException
    {
        response.setStatus(HttpStatus.ERROR);
        response.setContentType("application/json;charset=UTF-8");
        ApiResponse<?> body = ApiResponse.errorWithCode(
                HttpStatus.ERROR,
                "Gateway identity headers missing",
                ErrorCodeName.GATEWAY_IDENTITY_MISSING);
        response.getWriter().write(OBJECT_MAPPER.writeValueAsString(body));
    }

    private static String resolveClientIp(HttpServletRequest request)
    {
        String forwardedFor = request.getHeader("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank())
        {
            return forwardedFor.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }

    private static String sanitize(String raw)
    {
        if (raw == null)
        {
            return "<null>";
        }
        if (raw.length() > 64)
        {
            return raw.substring(0, 64) + "...";
        }
        return raw;
    }
}
