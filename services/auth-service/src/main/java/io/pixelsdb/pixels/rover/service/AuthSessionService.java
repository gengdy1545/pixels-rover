package io.pixelsdb.pixels.rover.service;

import io.pixelsdb.pixels.rover.rest.response.AccessTokenResponse;
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import io.pixelsdb.pixels.rover.rest.response.UserSessionResponse;

import java.util.List;

public interface AuthSessionService
{
    TokenResponse createSession(String username, Long userId, String userAgent, String clientIp);

    AccessTokenResponse refreshSession(String refreshToken, String userAgent, String clientIp);

    List<UserSessionResponse> listSessions(Long userId, String currentSessionId);

    void revokeSession(Long userId, String sessionId, String reason);

    void revokeOtherSessions(Long userId, String currentSessionId, String reason);

    void revokeAllSessions(Long userId, String reason);

    boolean isSessionActive(String sessionId);
}
