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

import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.config.security.CookieHelper;
import io.pixelsdb.pixels.rover.rest.request.LoginRequest;
import io.pixelsdb.pixels.rover.rest.request.RegisterRequest;
import io.pixelsdb.pixels.rover.rest.response.AccessTokenResponse;
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import io.pixelsdb.pixels.rover.service.SysLoginService;
import io.pixelsdb.pixels.rover.service.UserService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

/**
 * Authentication REST controller providing login, register, captcha, refresh, and user-info
 * endpoints.
 *
 * <p>User-facing endpoints ({@code /me}, {@code /logout}, {@code /logout-all},
 * {@code /sessions*}) consume identity exclusively from the gateway-injected
 * {@code X-Auth-User-Id} / {@code X-Auth-Session-Id} headers (see {@code backend.md §3.1}
 * and {@code §3.4}). Missing / malformed headers are rejected upstream by
 * {@link io.pixelsdb.pixels.rover.config.security.IdentityHeaderValidationFilter}.</p>
 *
 * @author pixels
 */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController
{
    private static final String USER_ID_HEADER = "X-Auth-User-Id";
    private static final String SESSION_ID_HEADER = "X-Auth-Session-Id";

    private final SysLoginService sysLoginService;
    private final UserService userService;
    private final CookieHelper cookieHelper;

    public AuthController(SysLoginService sysLoginService, UserService userService,
                          CookieHelper cookieHelper)
    {
        this.sysLoginService = sysLoginService;
        this.userService = userService;
        this.cookieHelper = cookieHelper;
    }

    /**
     * Login endpoint. Validates credentials and captcha, then writes cookies directly.
     */
    @PostMapping("/login")
    public ApiResponse<?> login(@Valid @RequestBody LoginRequest request,
                                HttpServletRequest httpRequest,
                                HttpServletResponse httpResponse)
    {
        TokenResponse tokenResponse = sysLoginService.login(request,
                resolveUserAgent(httpRequest), resolveClientIp(httpRequest));
        cookieHelper.writeTokenCookies(httpResponse, tokenResponse.getAccessToken(), tokenResponse.getRefreshToken());
        return ApiResponse.success("Login success", null);
    }

    /**
     * Register endpoint. Creates a new user account.
     */
    @PostMapping("/register")
    public ApiResponse<?> register(@Valid @RequestBody RegisterRequest request)
    {
        sysLoginService.verifyCaptcha(request.getCaptchaKey(), request.getCaptcha());
        userService.register(request);
        return ApiResponse.success("Registration successful", null);
    }

    /**
     * Captcha endpoint. Generates a captcha image and returns it as Base64.
     */
    @GetMapping("/captcha")
    public ApiResponse<?> getCaptcha()
    {
        return ApiResponse.success(sysLoginService.generateCaptcha());
    }

    /**
     * Refresh token endpoint. Reads refresh token from HttpOnly cookie only.
     *
     * <p>Hard boundary (see {@code backend.md §3.4}): this controller never uses
     * {@code SecurityContextHolder} nor decodes the refresh token JWT itself — the cookie
     * value is handed to {@link SysLoginService} as an opaque string and all JWT-level
     * checks (signature, session activeness, reuse) are service-layer domain logic.</p>
     */
    @PostMapping("/refresh")
    public ApiResponse<?> refreshToken(HttpServletRequest httpRequest,
                                       HttpServletResponse httpResponse)
    {
        String refreshToken = cookieHelper.resolveRefreshToken(httpRequest);
        if (refreshToken == null || refreshToken.isBlank())
        {
            return ApiResponse.error(
                    io.pixelsdb.pixels.rover.constant.ErrorCode.INVALID_ARGUMENT,
                    "Refresh token is required");
        }

        AccessTokenResponse tokenResponse = sysLoginService.refreshToken(refreshToken,
                resolveUserAgent(httpRequest), resolveClientIp(httpRequest));
        cookieHelper.writeTokenCookies(httpResponse, tokenResponse.getAccessToken(), tokenResponse.getRefreshToken());
        return ApiResponse.success("Token refreshed", null);
    }

    /**
     * Returns the current user's info, identified by the gateway-injected
     * {@code X-Auth-User-Id} header.
     */
    @GetMapping("/me")
    public ApiResponse<?> me(@RequestHeader(name = USER_ID_HEADER) Long userId)
    {
        return ApiResponse.success(userService.getUserInfoById(userId));
    }

    @PostMapping("/logout")
    public ApiResponse<?> logout(@RequestHeader(name = USER_ID_HEADER) Long userId,
                                 HttpServletRequest request,
                                 HttpServletResponse response)
    {
        String sessionId = resolveCurrentSessionId(request);
        if (sessionId != null && !sessionId.isBlank())
        {
            sysLoginService.revokeSessionById(userId, sessionId);
        }
        cookieHelper.clearTokenCookies(response);
        return ApiResponse.success("Logged out", null);
    }

    @PostMapping("/logout-all")
    public ApiResponse<?> logoutAll(@RequestHeader(name = USER_ID_HEADER) Long userId,
                                    HttpServletResponse response)
    {
        sysLoginService.revokeAllSessionsById(userId);
        cookieHelper.clearTokenCookies(response);
        return ApiResponse.success("Logged out from all sessions", null);
    }

    @GetMapping("/user-info")
    public ApiResponse<?> getUserInfo(@RequestHeader(name = USER_ID_HEADER) Long userId)
    {
        return ApiResponse.success(userService.getUserInfoById(userId));
    }

    @GetMapping("/sessions")
    public ApiResponse<?> listSessions(@RequestHeader(name = USER_ID_HEADER) Long userId,
                                       HttpServletRequest request)
    {
        return ApiResponse.success(
                sysLoginService.listSessionsById(userId, resolveCurrentSessionId(request))
        );
    }

    @DeleteMapping("/sessions/{sessionId}")
    public ApiResponse<?> revokeSession(@PathVariable String sessionId,
                                        @RequestHeader(name = USER_ID_HEADER) Long userId,
                                        HttpServletRequest request,
                                        HttpServletResponse response)
    {
        sysLoginService.revokeSessionById(userId, sessionId);
        String currentSessionId = resolveCurrentSessionId(request);
        boolean revokedCurrentSession = currentSessionId != null && sessionId.equals(currentSessionId);
        if (revokedCurrentSession)
        {
            cookieHelper.clearTokenCookies(response);
        }
        String message = revokedCurrentSession ? "Current session revoked" : "Session revoked";
        return ApiResponse.success(message, null);
    }

    /**
     * Reads the current session id directly from the gateway-injected {@code X-Auth-Session-Id}
     * header. Under the cookie-only model there is no {@code Authorization: Bearer} fallback —
     * session id is part of the identity envelope the gateway attaches after successful
     * introspect (see {@code backend.md §3.1}).
     */
    private static String resolveCurrentSessionId(HttpServletRequest request)
    {
        String header = request.getHeader(SESSION_ID_HEADER);
        if (header == null || header.isBlank())
        {
            return null;
        }
        return header;
    }

    private static String resolveUserAgent(HttpServletRequest request)
    {
        return request.getHeader("User-Agent");
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
}
