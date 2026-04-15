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
import org.springframework.stereotype.Component;

/**
 * Helper for reading authentication cookies from incoming requests.
 *
 * <p>Cookie writing and clearing has been migrated to the API gateway (NJS).
 * This class now only provides read-only access to cookie values for
 * JWT authentication and token refresh flows.</p>
 *
 * @author pixels
 */
@Component
public class CookieHelper
{
    public static final String ACCESS_TOKEN_COOKIE = "access_token";
    public static final String REFRESH_TOKEN_COOKIE = "refresh_token";

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
}
