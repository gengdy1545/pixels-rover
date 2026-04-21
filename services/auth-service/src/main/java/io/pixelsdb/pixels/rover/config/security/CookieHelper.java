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

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * Helper for reading and writing authentication cookies.
 *
 * @author pixels
 */
@Component
public class CookieHelper
{
    public static final String ACCESS_TOKEN_COOKIE = "access_token";
    public static final String REFRESH_TOKEN_COOKIE = "refresh_token";
    public static final String XSRF_TOKEN_COOKIE = "XSRF-TOKEN";
    public static final String LOGGED_IN_COOKIE = "logged_in";
    private static final String REFRESH_TOKEN_PATH = "/api/v1/auth/refresh";

    private final boolean secure;
    private final String sameSite;
    private final String domain;
    private final long accessTokenMaxAge;
    private final long refreshTokenMaxAge;

    public CookieHelper(
            @Value("${cookie.secure:false}") boolean secure,
            @Value("${cookie.same-site:Lax}") String sameSite,
            @Value("${cookie.domain:}") String domain,
            @Value("${jwt.access-token-expiration-ms:3600000}") long accessTokenExpirationMs,
            @Value("${jwt.refresh-token-expiration-ms:604800000}") long refreshTokenExpirationMs)
    {
        this.secure = secure;
        this.sameSite = sameSite;
        this.domain = domain == null ? "" : domain.trim();
        this.accessTokenMaxAge = Math.max(1L, accessTokenExpirationMs / 1000L);
        this.refreshTokenMaxAge = Math.max(1L, refreshTokenExpirationMs / 1000L);
    }

    /**
     * Read the access_token value from the request cookies.
     */
    public String resolveAccessToken(jakarta.servlet.http.HttpServletRequest request)
    {
        if (request.getCookies() == null)
        {
            return null;
        }
        for (Cookie cookie : request.getCookies())
        {
            if (ACCESS_TOKEN_COOKIE.equals(cookie.getName()))
            {
                return cookie.getValue();
            }
        }
        return null;
    }

    /**
     * Read the refresh_token value from the request cookies.
     */
    public String resolveRefreshToken(jakarta.servlet.http.HttpServletRequest request)
    {
        if (request.getCookies() == null)
        {
            return null;
        }
        for (Cookie cookie : request.getCookies())
        {
            if (REFRESH_TOKEN_COOKIE.equals(cookie.getName()))
            {
                return cookie.getValue();
            }
        }
        return null;
    }

    public void writeTokenCookies(HttpServletResponse response, String accessToken, String refreshToken)
    {
        if (accessToken != null && !accessToken.isBlank())
        {
            addCookie(response, ACCESS_TOKEN_COOKIE, accessToken, "/", accessTokenMaxAge, true);
            addCookie(response, XSRF_TOKEN_COOKIE, UUID.randomUUID().toString(), "/", refreshTokenMaxAge, false);
            addCookie(response, LOGGED_IN_COOKIE, "true", "/", refreshTokenMaxAge, false);
        }

        if (refreshToken != null && !refreshToken.isBlank())
        {
            addCookie(response, REFRESH_TOKEN_COOKIE, refreshToken, REFRESH_TOKEN_PATH, refreshTokenMaxAge, true);
        }
    }

    public void clearTokenCookies(HttpServletResponse response)
    {
        addCookie(response, ACCESS_TOKEN_COOKIE, "", "/", 0, true);
        addCookie(response, REFRESH_TOKEN_COOKIE, "", REFRESH_TOKEN_PATH, 0, true);
        addCookie(response, XSRF_TOKEN_COOKIE, "", "/", 0, false);
        addCookie(response, LOGGED_IN_COOKIE, "", "/", 0, false);
    }

    private void addCookie(HttpServletResponse response,
                           String name,
                           String value,
                           String path,
                           long maxAgeSeconds,
                           boolean httpOnly)
    {
        ResponseCookie.ResponseCookieBuilder builder = ResponseCookie.from(name, value)
                .path(path)
                .httpOnly(httpOnly)
                .secure(secure)
                .sameSite(sameSite)
                .maxAge(maxAgeSeconds);

        if (!domain.isBlank())
        {
            builder.domain(domain);
        }

        response.addHeader("Set-Cookie", builder.build().toString());
    }
}
