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
import org.springframework.stereotype.Component;

import java.util.UUID;

/**
 * Helper for writing and clearing HttpOnly authentication cookies and CSRF tokens.
 *
 * <p>Cookie attributes are controlled via application.properties so that
 * dev (HTTP / localhost) and prod (HTTPS / real domain) can use different settings.</p>
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

    @Value("${cookie.secure:false}")
    private boolean secure;

    @Value("${cookie.same-site:Lax}")
    private String sameSite;

    @Value("${cookie.domain:}")
    private String domain;

    @Value("${jwt.access-token-expiration-ms:3600000}")
    private long accessTokenExpirationMs;

    @Value("${jwt.refresh-token-expiration-ms:604800000}")
    private long refreshTokenExpirationMs;

    /**
     * Write access_token, refresh_token, XSRF-TOKEN, and logged_in cookies after login or refresh.
     */
    public void writeTokenCookies(HttpServletResponse response, String accessToken, String refreshToken)
    {
        addCookie(response, ACCESS_TOKEN_COOKIE, accessToken,
                "/", (int) (accessTokenExpirationMs / 1000), true);

        addCookie(response, REFRESH_TOKEN_COOKIE, refreshToken,
                REFRESH_TOKEN_PATH, (int) (refreshTokenExpirationMs / 1000), true);

        // Non-HttpOnly CSRF token — readable by JavaScript
        addCookie(response, XSRF_TOKEN_COOKIE, UUID.randomUUID().toString(),
                "/", (int) (accessTokenExpirationMs / 1000), false);

        // Non-HttpOnly login indicator — readable by JavaScript for UI state
        addCookie(response, LOGGED_IN_COOKIE, "true",
                "/", (int) (refreshTokenExpirationMs / 1000), false);
    }

    /**
     * Clear all authentication cookies on logout.
     */
    public void clearTokenCookies(HttpServletResponse response)
    {
        clearCookie(response, ACCESS_TOKEN_COOKIE, "/");
        clearCookie(response, REFRESH_TOKEN_COOKIE, REFRESH_TOKEN_PATH);
        clearCookie(response, XSRF_TOKEN_COOKIE, "/");
        clearCookie(response, LOGGED_IN_COOKIE, "/");
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

    private void addCookie(HttpServletResponse response, String name, String value,
                           String path, int maxAgeSeconds, boolean httpOnly)
    {
        StringBuilder sb = new StringBuilder();
        sb.append(name).append("=").append(value);
        sb.append("; Path=").append(path);
        sb.append("; Max-Age=").append(maxAgeSeconds);
        sb.append("; SameSite=").append(sameSite);
        if (httpOnly)
        {
            sb.append("; HttpOnly");
        }
        if (secure)
        {
            sb.append("; Secure");
        }
        if (domain != null && !domain.isBlank())
        {
            sb.append("; Domain=").append(domain);
        }
        response.addHeader("Set-Cookie", sb.toString());
    }

    private void clearCookie(HttpServletResponse response, String name, String path)
    {
        StringBuilder sb = new StringBuilder();
        sb.append(name).append("=");
        sb.append("; Path=").append(path);
        sb.append("; Max-Age=0");
        sb.append("; SameSite=").append(sameSite);
        sb.append("; HttpOnly");
        if (secure)
        {
            sb.append("; Secure");
        }
        if (domain != null && !domain.isBlank())
        {
            sb.append("; Domain=").append(domain);
        }
        response.addHeader("Set-Cookie", sb.toString());
    }
}
