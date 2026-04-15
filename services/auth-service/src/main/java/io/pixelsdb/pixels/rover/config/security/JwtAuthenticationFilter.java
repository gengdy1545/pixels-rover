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

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import io.pixelsdb.pixels.rover.service.AuthSessionService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * JWT authentication filter that extracts and validates JWT tokens from request headers.
 *
 * @author pixels
 */
public class JwtAuthenticationFilter extends OncePerRequestFilter
{
    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);
    private static final String AUTHORIZATION_HEADER = "Authorization";
    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtTokenProvider jwtTokenProvider;
    private final UserDetailsService userDetailsService;
    private final AuthSessionService authSessionService;

    public JwtAuthenticationFilter(JwtTokenProvider jwtTokenProvider,
                                   UserDetailsService userDetailsService,
                                   AuthSessionService authSessionService)
    {
        this.jwtTokenProvider = jwtTokenProvider;
        this.userDetailsService = userDetailsService;
        this.authSessionService = authSessionService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException
    {
        try
        {
            String jwt = extractJwtFromRequest(request);
            if (jwt != null && jwtTokenProvider.validateToken(jwt))
            {
                if (!"access".equals(jwtTokenProvider.getTokenType(jwt)))
                {
                    filterChain.doFilter(request, response);
                    return;
                }
                String sessionId = jwtTokenProvider.getSessionIdFromToken(jwt);
                if (!authSessionService.isSessionActive(sessionId))
                {
                    log.warn("Rejected revoked or expired session: {}", sessionId);
                    filterChain.doFilter(request, response);
                    return;
                }
                String username = jwtTokenProvider.getUsernameFromToken(jwt);
                UserDetails userDetails = userDetailsService.loadUserByUsername(username);

                UsernamePasswordAuthenticationToken authentication =
                        new UsernamePasswordAuthenticationToken(userDetails, null, userDetails.getAuthorities());
                authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));

                SecurityContextHolder.getContext().setAuthentication(authentication);

                // Put userId into MDC for structured logging
                Long userId = jwtTokenProvider.getUserIdFromToken(jwt);
                if (userId != null)
                {
                    MDC.put("userId", userId.toString());
                }
            }
        }
        catch (Exception e)
        {
            log.error("Cannot set user authentication: {}", e.getMessage());
        }

        filterChain.doFilter(request, response);
    }

    /**
     * Extract JWT token from the request.
     * Priority: access_token Cookie > Authorization header.
     */
    private String extractJwtFromRequest(HttpServletRequest request)
    {
        // 1. Try HttpOnly Cookie first
        if (request.getCookies() != null)
        {
            for (Cookie cookie : request.getCookies())
            {
                if (CookieHelper.ACCESS_TOKEN_COOKIE.equals(cookie.getName()))
                {
                    String value = cookie.getValue();
                    if (StringUtils.hasText(value))
                    {
                        return value;
                    }
                }
            }
        }

        // 2. Fall back to Authorization header (backward compat & non-browser clients)
        String bearerToken = request.getHeader(AUTHORIZATION_HEADER);
        if (StringUtils.hasText(bearerToken) && bearerToken.startsWith(BEARER_PREFIX))
        {
            return bearerToken.substring(BEARER_PREFIX.length());
        }
        return null;
    }
}
