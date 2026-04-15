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
import io.pixelsdb.pixels.rover.config.security.JwtTokenProvider;
import io.pixelsdb.pixels.rover.rest.request.LoginRequest;
import io.pixelsdb.pixels.rover.rest.request.RefreshTokenRequest;
import io.pixelsdb.pixels.rover.rest.request.RegisterRequest;
import jakarta.servlet.http.HttpServletRequest;
import io.pixelsdb.pixels.rover.service.SysLoginService;
import io.pixelsdb.pixels.rover.service.UserService;
import jakarta.validation.Valid;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * Authentication REST controller providing login, register, captcha, refresh, and user-info endpoints.
 *
 * @author pixels
 */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController
{
    private final SysLoginService sysLoginService;
    private final UserService userService;
    private final JwtTokenProvider jwtTokenProvider;
    private final CookieHelper cookieHelper;

    public AuthController(SysLoginService sysLoginService, UserService userService,
                          JwtTokenProvider jwtTokenProvider, CookieHelper cookieHelper)
    {
        this.sysLoginService = sysLoginService;
        this.userService = userService;
        this.jwtTokenProvider = jwtTokenProvider;
        this.cookieHelper = cookieHelper;
    }

    /**
     * Login endpoint. Validates credentials and captcha, returns JWT tokens
     * in the response body. Cookie injection is handled by the API gateway.
     */
    @PostMapping("/login")
    public ApiResponse<?> login(@Valid @RequestBody LoginRequest request,
                                HttpServletRequest httpRequest)
    {
        var tokenResponse = sysLoginService.login(request,
                resolveUserAgent(httpRequest), resolveClientIp(httpRequest));
        return ApiResponse.success("Login success", tokenResponse);
    }

    /**
     * Register endpoint. Creates a new user account.
     */
    @PostMapping("/register")
    public ApiResponse<?> register(@Valid @RequestBody RegisterRequest request)
    {
        sysLoginService.verifyCaptcha(request.getCaptchaKey(), request.getCaptcha());
        userService.register(request);
        return ApiResponse.success("Registration successful");
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
     * Refresh token endpoint. Reads refresh token from Cookie first, then falls back to request body.
     * Cookie injection for new tokens is handled by the API gateway.
     */
    @PostMapping("/refresh")
    public ApiResponse<?> refreshToken(@RequestBody(required = false) RefreshTokenRequest request,
                                       HttpServletRequest httpRequest)
    {
        // Prefer refresh_token from Cookie; fall back to request body
        String refreshToken = cookieHelper.resolveRefreshToken(httpRequest);
        if (refreshToken == null && request != null)
        {
            refreshToken = request.getRefreshToken();
        }
        if (refreshToken == null || refreshToken.isBlank())
        {
            return ApiResponse.error(
                    io.pixelsdb.pixels.rover.constant.ErrorCode.INVALID_ARGUMENT,
                    "Refresh token is required");
        }

        var tokenResponse = sysLoginService.refreshToken(refreshToken,
                resolveUserAgent(httpRequest), resolveClientIp(httpRequest));
        return ApiResponse.success("Token refreshed", tokenResponse);
    }

    /**
     * Lightweight login-state check. Returns current user info if authenticated.
     * Used by the frontend to determine login state when using HttpOnly cookies.
     */
    @GetMapping("/me")
    public ApiResponse<?> me()
    {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()
                || "anonymousUser".equals(authentication.getPrincipal()))
        {
            return ApiResponse.unauthorized("Not authenticated");
        }
        return ApiResponse.success(userService.getUserInfo(authentication.getName()));
    }

    /**
     * Get current user info endpoint.
     */
    @GetMapping("/user-info")
    public ApiResponse<?> getUserInfo()
    {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated())
        {
            return ApiResponse.unauthorized("Not authenticated");
        }

        return ApiResponse.success(userService.getUserInfo(authentication.getName()));
    }

    /**
     * Public JWKS endpoint for RSA verification consumers.
     */
    @GetMapping("/jwks")
    public ApiResponse<?> getJwks()
    {
        return ApiResponse.success(jwtTokenProvider.getPublicJwks());
    }

    @GetMapping("/sessions")
    public ApiResponse<?> listSessions(HttpServletRequest request)
    {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        return ApiResponse.success(
                sysLoginService.listSessions(authentication.getName(), resolveCurrentSessionId(request))
        );
    }

    @PostMapping("/logout")
    public ApiResponse<?> logout(HttpServletRequest request)
    {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        sysLoginService.revokeSession(authentication.getName(), resolveCurrentSessionId(request));
        return ApiResponse.success("Logged out");
    }

    @PostMapping("/logout-all")
    public ApiResponse<?> logoutAll(HttpServletRequest request)
    {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        sysLoginService.revokeOtherSessions(authentication.getName(), resolveCurrentSessionId(request));
        return ApiResponse.success("Logged out from other sessions");
    }

    @DeleteMapping("/sessions/{sessionId}")
    public ApiResponse<?> revokeSession(@PathVariable String sessionId, HttpServletRequest request)
    {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        sysLoginService.revokeSession(authentication.getName(), sessionId);
        String currentSessionId = resolveCurrentSessionId(request);
        String message = currentSessionId != null && sessionId.equals(currentSessionId)
                ? "Current session revoked"
                : "Session revoked";
        return ApiResponse.success(message);
    }

    private String resolveCurrentSessionId(HttpServletRequest request)
    {
        // Try Cookie first, then Authorization header
        String token = cookieHelper.resolveAccessToken(request);
        if (token == null)
        {
            String authorization = request.getHeader("Authorization");
            if (authorization != null && authorization.startsWith("Bearer "))
            {
                token = authorization.substring("Bearer ".length());
            }
        }
        if (token == null)
        {
            return null;
        }
        try
        {
            return jwtTokenProvider.getSessionIdFromToken(token);
        }
        catch (Exception e)
        {
            return null;
        }
    }

    private String resolveUserAgent(HttpServletRequest request)
    {
        return request.getHeader("User-Agent");
    }

    private String resolveClientIp(HttpServletRequest request)
    {
        String forwardedFor = request.getHeader("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank())
        {
            return forwardedFor.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
