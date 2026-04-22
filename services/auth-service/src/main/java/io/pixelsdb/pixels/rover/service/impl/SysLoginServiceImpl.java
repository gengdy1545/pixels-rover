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
package io.pixelsdb.pixels.rover.service.impl;

import com.google.code.kaptcha.Producer;
import io.pixelsdb.pixels.rover.config.security.PixelsUserDetails;
import io.pixelsdb.pixels.rover.constant.ErrorCode;
import io.pixelsdb.pixels.rover.exception.ServiceException;
import io.pixelsdb.pixels.rover.mapper.UserRepository;
import io.pixelsdb.pixels.rover.model.User;
import io.pixelsdb.pixels.rover.rest.request.LoginRequest;
import io.pixelsdb.pixels.rover.rest.response.AccessTokenResponse;
import io.pixelsdb.pixels.rover.rest.response.CaptchaResponse;
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import io.pixelsdb.pixels.rover.rest.response.UserSessionResponse;
import io.pixelsdb.pixels.rover.service.AuthSessionService;
import io.pixelsdb.pixels.rover.service.SysLoginService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.Base64;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class SysLoginServiceImpl implements SysLoginService
{
    private final AuthenticationManager authenticationManager;
    private final UserRepository userRepository;
    private final AuthSessionService authSessionService;
    private final Producer captchaProducer;
    private final Producer captchaProducerMath;

    @Value("${user.captchaType}")
    private String captchaType;

    /**
     * In-memory captcha store. In production, consider using Redis.
     */
    private final ConcurrentHashMap<String, String> captchaStore = new ConcurrentHashMap<>();

    public SysLoginServiceImpl(
            AuthenticationManager authenticationManager,
            UserRepository userRepository,
            AuthSessionService authSessionService,
            Producer captchaProducer,
            Producer captchaProducerMath)
    {
        this.authenticationManager = authenticationManager;
        this.userRepository = userRepository;
        this.authSessionService = authSessionService;
        this.captchaProducer = captchaProducer;
        this.captchaProducerMath = captchaProducerMath;
    }

    @Override
    public TokenResponse login(LoginRequest request, String userAgent, String clientIp)
    {
        verifyCaptcha(request.getCaptchaKey(), request.getCaptcha());

        Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(request.getUsername(), request.getPassword())
        );

        Object principal = authentication.getPrincipal();
        if (!(principal instanceof PixelsUserDetails))
        {
            throw new ServiceException("Authenticated principal is invalid", ErrorCode.INTERNAL_ERROR);
        }
        PixelsUserDetails userDetails = (PixelsUserDetails) principal;
        Long userId = userDetails.getId();
        return authSessionService.createSession(authentication.getName(), userId, userAgent, clientIp);
    }

    @Override
    public CaptchaResponse generateCaptcha()
    {
        try
        {
            String capStr;
            String code;
            BufferedImage image;

            if ("math".equals(captchaType))
            {
                String capText = captchaProducerMath.createText();
                capStr = capText.substring(0, capText.lastIndexOf("@"));
                code = capText.substring(capText.lastIndexOf("@") + 1);
                image = captchaProducerMath.createImage(capStr);
            }
            else
            {
                capStr = captchaProducer.createText();
                code = capStr;
                image = captchaProducer.createImage(capStr);
            }

            String captchaKey = UUID.randomUUID().toString();
            captchaStore.put(captchaKey, code);

            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            ImageIO.write(image, "jpg", baos);

            return new CaptchaResponse(
                    captchaKey,
                    "data:image/jpeg;base64," + Base64.getEncoder().encodeToString(baos.toByteArray())
            );
        }
        catch (Exception e)
        {
            throw new ServiceException("Failed to generate captcha", ErrorCode.INTERNAL_ERROR);
        }
    }

    @Override
    public AccessTokenResponse refreshToken(String refreshToken, String userAgent, String clientIp)
    {
        return authSessionService.refreshSession(refreshToken, userAgent, clientIp);
    }

    @Override
    public List<UserSessionResponse> listSessionsById(Long userId, String currentSessionId)
    {
        requireUser(userId);
        return authSessionService.listSessions(userId, currentSessionId);
    }

    @Override
    public void revokeSessionById(Long userId, String sessionId)
    {
        requireUser(userId);
        authSessionService.revokeSession(userId, sessionId, "user_logout");
    }

    @Override
    public void revokeAllSessionsById(Long userId)
    {
        requireUser(userId);
        authSessionService.revokeAllSessions(userId, "user_logout_all");
    }

    private void requireUser(Long userId)
    {
        if (userId == null)
        {
            throw new ServiceException("User not found", ErrorCode.RESOURCE_NOT_FOUND);
        }
        User user = userRepository.findById(userId.longValue());
        if (user == null)
        {
            throw new ServiceException("User not found", ErrorCode.RESOURCE_NOT_FOUND);
        }
    }

    @Override
    public void verifyCaptcha(String captchaKey, String captcha)
    {
        if (captchaKey == null || captcha == null)
        {
            return;
        }

        String storedCaptcha = captchaStore.remove(captchaKey);
        if (storedCaptcha == null || !storedCaptcha.equals(captcha))
        {
            throw new ServiceException("Verification code error", ErrorCode.INVALID_ARGUMENT);
        }
    }
}
