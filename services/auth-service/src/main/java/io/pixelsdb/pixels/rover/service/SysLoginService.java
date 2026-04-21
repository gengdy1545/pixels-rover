/*
 * Copyright 2023 PixelsDB.
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
package io.pixelsdb.pixels.rover.service;

import io.pixelsdb.pixels.rover.rest.request.LoginRequest;
import io.pixelsdb.pixels.rover.rest.response.AccessTokenResponse;
import io.pixelsdb.pixels.rover.rest.response.CaptchaResponse;
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import io.pixelsdb.pixels.rover.rest.response.UserSessionResponse;

import java.util.List;

public interface SysLoginService
{
    TokenResponse login(LoginRequest request, String userAgent, String clientIp);

    CaptchaResponse generateCaptcha();

    AccessTokenResponse refreshToken(String refreshToken, String userAgent, String clientIp);

    List<UserSessionResponse> listSessions(String username, String currentSessionId);

    void revokeSession(String username, String sessionId);

    void revokeOtherSessions(String username, String currentSessionId);

    void revokeAllSessions(String username);

    void verifyCaptcha(String captchaKey, String captcha);
}
