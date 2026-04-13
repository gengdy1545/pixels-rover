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

import com.google.code.kaptcha.Producer;
import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.config.security.JwtTokenProvider;
import io.pixelsdb.pixels.rover.config.security.PixelsUserDetails;
import io.pixelsdb.pixels.rover.constant.HttpStatus;
import io.pixelsdb.pixels.rover.mapper.UserRepository;
import io.pixelsdb.pixels.rover.model.User;
import io.pixelsdb.pixels.rover.rest.request.LoginRequest;
import io.pixelsdb.pixels.rover.rest.request.RefreshTokenRequest;
import io.pixelsdb.pixels.rover.rest.request.RegisterRequest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.sql.Timestamp;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Authentication REST controller providing login, register, captcha, refresh, and user-info endpoints.
 *
 * @author pixels
 */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController
{
    @Autowired
    private AuthenticationManager authenticationManager;

    @Autowired
    private JwtTokenProvider jwtTokenProvider;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private Producer captchaProducer;

    @Autowired
    private Producer captchaProducerMath;

    @Value("${user.captchaType}")
    private String captchaType;

    /**
     * In-memory captcha store. In production, consider using Redis.
     */
    private final ConcurrentHashMap<String, String> captchaStore = new ConcurrentHashMap<>();

    /**
     * Login endpoint. Validates credentials and captcha, returns JWT tokens.
     */
    @PostMapping("/login")
    public ApiResponse<?> login(@RequestBody LoginRequest request)
    {
        // Validate captcha
        if (request.getCaptchaKey() != null && request.getCaptcha() != null)
        {
            String storedCaptcha = captchaStore.remove(request.getCaptchaKey());
            if (storedCaptcha == null || !storedCaptcha.equals(request.getCaptcha()))
            {
                return ApiResponse.error(HttpStatus.BAD_REQUEST, "Verification code error");
            }
        }

        // Authenticate
        Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(request.getUsername(), request.getPassword())
        );

        // Generate tokens
        String accessToken = jwtTokenProvider.generateAccessToken(authentication);
        String refreshToken = jwtTokenProvider.generateRefreshToken(authentication);

        Map<String, String> tokenData = new HashMap<>();
        tokenData.put("accessToken", accessToken);
        tokenData.put("refreshToken", refreshToken);

        return ApiResponse.success("Login success", tokenData);
    }

    /**
     * Register endpoint. Creates a new user account.
     */
    @PostMapping("/register")
    public ApiResponse<?> register(@RequestBody RegisterRequest request)
    {
        // Validate captcha
        if (request.getCaptchaKey() != null && request.getCaptcha() != null)
        {
            String storedCaptcha = captchaStore.remove(request.getCaptchaKey());
            if (storedCaptcha == null || !storedCaptcha.equals(request.getCaptcha()))
            {
                return ApiResponse.error(HttpStatus.BAD_REQUEST, "Verification code error");
            }
        }

        // Check if user already exists
        User existUser = userRepository.findByEmail(request.getEmail());
        if (existUser != null)
        {
            return ApiResponse.error(HttpStatus.BAD_REQUEST, "User already exists");
        }

        // Create new user
        User user = new User();
        user.setName(request.getName());
        user.setEmail(request.getEmail());
        user.setAffiliation(request.getAffiliation());
        user.setPassword(passwordEncoder.encode(request.getPassword()));
        user.setCreateTime(new Timestamp(System.currentTimeMillis()));
        userRepository.save(user);

        return ApiResponse.success("Registration successful");
    }

    /**
     * Captcha endpoint. Generates a captcha image and returns it as Base64.
     */
    @GetMapping("/captcha")
    public ApiResponse<?> getCaptcha()
    {
        try
        {
            String capStr;
            String code;
            BufferedImage bi;

            if ("math".equals(captchaType))
            {
                String capText = captchaProducerMath.createText();
                capStr = capText.substring(0, capText.lastIndexOf("@"));
                code = capText.substring(capText.lastIndexOf("@") + 1);
                bi = captchaProducerMath.createImage(capStr);
            }
            else
            {
                capStr = code = captchaProducer.createText();
                bi = captchaProducer.createImage(capStr);
            }

            // Store captcha with a unique key
            String captchaKey = UUID.randomUUID().toString();
            captchaStore.put(captchaKey, code);

            // Convert image to Base64
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            ImageIO.write(bi, "jpg", baos);
            String base64Image = Base64.getEncoder().encodeToString(baos.toByteArray());

            Map<String, String> captchaData = new HashMap<>();
            captchaData.put("captchaKey", captchaKey);
            captchaData.put("captchaImage", "data:image/jpeg;base64," + base64Image);

            return ApiResponse.success(captchaData);
        }
        catch (Exception e)
        {
            return ApiResponse.error("Failed to generate captcha");
        }
    }

    /**
     * Refresh token endpoint. Validates refresh token and returns a new access token.
     */
    @PostMapping("/refresh")
    public ApiResponse<?> refreshToken(@RequestBody RefreshTokenRequest request)
    {
        String refreshToken = request.getRefreshToken();

        if (!jwtTokenProvider.validateToken(refreshToken))
        {
            return ApiResponse.error(HttpStatus.UNAUTHORIZED, "Invalid or expired refresh token");
        }

        String tokenType = jwtTokenProvider.getTokenType(refreshToken);
        if (!"refresh".equals(tokenType))
        {
            return ApiResponse.error(HttpStatus.BAD_REQUEST, "Invalid token type");
        }

        String username = jwtTokenProvider.getUsernameFromToken(refreshToken);
        String newAccessToken = jwtTokenProvider.generateAccessToken(username);

        Map<String, String> tokenData = new HashMap<>();
        tokenData.put("accessToken", newAccessToken);

        return ApiResponse.success("Token refreshed", tokenData);
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

        String email = authentication.getName();
        User user = userRepository.findByEmail(email);
        if (user == null)
        {
            return ApiResponse.error(HttpStatus.NOT_FOUND, "User not found");
        }

        Map<String, Object> userInfo = new HashMap<>();
        userInfo.put("id", user.getId());
        userInfo.put("name", user.getName());
        userInfo.put("email", user.getEmail());
        userInfo.put("affiliation", user.getAffiliation());

        return ApiResponse.success(userInfo);
    }
}
