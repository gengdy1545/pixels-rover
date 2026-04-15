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
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.authentication.AuthenticationSuccessHandler;

import java.io.IOException;

/**
 * Authentication success handler that returns JWT tokens in the response.
 *
 * @author pixels
 */
public class JsonAuthenticationSuccessHandler implements AuthenticationSuccessHandler
{
    private final JwtTokenProvider jwtTokenProvider;

    public JsonAuthenticationSuccessHandler(JwtTokenProvider jwtTokenProvider)
    {
        this.jwtTokenProvider = jwtTokenProvider;
    }

    @Override
    public void onAuthenticationSuccess(HttpServletRequest request, HttpServletResponse response,
                                        Authentication authentication) throws IOException, ServletException
    {
        TokenResponse tokenResponse = new TokenResponse(
                jwtTokenProvider.generateAccessToken(authentication),
                jwtTokenProvider.generateRefreshToken(authentication)
        );
        ApiResponse<TokenResponse> result = ApiResponse.success("Login success", tokenResponse);

        response.setContentType("application/json;charset=UTF-8");
        String jsonData = new ObjectMapper().writeValueAsString(result);
        response.getWriter().write(jsonData);
    }
}
