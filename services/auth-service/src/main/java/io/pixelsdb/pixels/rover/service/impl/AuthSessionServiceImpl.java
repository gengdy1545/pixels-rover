package io.pixelsdb.pixels.rover.service.impl;

import io.pixelsdb.pixels.rover.config.security.JwtTokenProvider;
import io.pixelsdb.pixels.rover.constant.ErrorCode;
import io.pixelsdb.pixels.rover.exception.ServiceException;
import io.pixelsdb.pixels.rover.mapper.AuthSessionRepository;
import io.pixelsdb.pixels.rover.model.AuthSession;
import io.pixelsdb.pixels.rover.rest.response.AccessTokenResponse;
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import io.pixelsdb.pixels.rover.rest.response.UserSessionResponse;
import io.pixelsdb.pixels.rover.service.AuthSessionService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

@Service
public class AuthSessionServiceImpl implements AuthSessionService
{
    private static final String REASON_LOGOUT = "user_logout";
    private static final String REASON_REFRESH_REUSE = "refresh_token_reuse_detected";

    private final JwtTokenProvider jwtTokenProvider;
    private final AuthSessionRepository authSessionRepository;

    public AuthSessionServiceImpl(JwtTokenProvider jwtTokenProvider, AuthSessionRepository authSessionRepository)
    {
        this.jwtTokenProvider = jwtTokenProvider;
        this.authSessionRepository = authSessionRepository;
    }

    @Override
    @Transactional
    public TokenResponse createSession(String username, Long userId, String userAgent, String clientIp)
    {
        String sessionId = UUID.randomUUID().toString();
        String refreshTokenId = UUID.randomUUID().toString();
        String accessToken = jwtTokenProvider.generateAccessToken(username, userId, sessionId);
        String refreshToken = jwtTokenProvider.generateRefreshToken(username, userId, sessionId, refreshTokenId);

        AuthSession session = new AuthSession();
        session.setSessionId(sessionId);
        session.setUserId(userId);
        session.setUserEmail(username);
        session.setCurrentRefreshTokenId(refreshTokenId);
        session.setRefreshTokenHash(hashToken(refreshToken));
        session.setRefreshTokenExpiresAt(new Timestamp(jwtTokenProvider.getExpirationFromToken(refreshToken).getTime()));
        session.setLastActivityAt(now());
        session.setUserAgent(limit(userAgent, 255));
        session.setClientIp(limit(clientIp, 64));
        authSessionRepository.save(session);

        return new TokenResponse(accessToken, refreshToken, sessionId);
    }

    @Override
    @Transactional
    public AccessTokenResponse refreshSession(String refreshToken, String userAgent, String clientIp)
    {
        if (!jwtTokenProvider.validateToken(refreshToken))
        {
            throw new ServiceException("Invalid or expired refresh token", ErrorCode.INVALID_TOKEN);
        }
        if (!"refresh".equals(jwtTokenProvider.getTokenType(refreshToken)))
        {
            throw new ServiceException("Invalid token type", ErrorCode.INVALID_TOKEN_TYPE);
        }

        String sessionId = jwtTokenProvider.getSessionIdFromToken(refreshToken);
        String refreshTokenId = jwtTokenProvider.getTokenIdFromToken(refreshToken);
        String username = jwtTokenProvider.getUsernameFromToken(refreshToken);
        Long userId = jwtTokenProvider.getUserIdFromToken(refreshToken);
        if (sessionId == null || refreshTokenId == null || username == null || userId == null)
        {
            throw new ServiceException("Invalid token payload", ErrorCode.INVALID_TOKEN);
        }

        AuthSession session = authSessionRepository.findBySessionId(sessionId)
                .orElseThrow(() -> new ServiceException("Invalid or expired refresh token", ErrorCode.INVALID_TOKEN));

        if (!Objects.equals(session.getUserId(), userId) || !Objects.equals(session.getUserEmail(), username))
        {
            revokeSessionInternal(session, REASON_REFRESH_REUSE);
            throw new ServiceException("Invalid or expired refresh token", ErrorCode.INVALID_TOKEN);
        }
        if (session.getRevokedAt() != null)
        {
            throw new ServiceException("Session has been revoked", ErrorCode.INVALID_TOKEN);
        }
        if (session.getRefreshTokenExpiresAt().before(now()))
        {
            revokeSessionInternal(session, "refresh_token_expired");
            throw new ServiceException("Invalid or expired refresh token", ErrorCode.INVALID_TOKEN);
        }

        String presentedHash = hashToken(refreshToken);
        if (!Objects.equals(session.getRefreshTokenHash(), presentedHash)
                || !Objects.equals(session.getCurrentRefreshTokenId(), refreshTokenId))
        {
            revokeSessionInternal(session, REASON_REFRESH_REUSE);
            throw new ServiceException("Refresh token reuse detected", ErrorCode.INVALID_TOKEN);
        }

        String nextRefreshTokenId = UUID.randomUUID().toString();
        String nextAccessToken = jwtTokenProvider.generateAccessToken(username, userId, sessionId);
        String nextRefreshToken = jwtTokenProvider.generateRefreshToken(username, userId, sessionId, nextRefreshTokenId);

        session.setCurrentRefreshTokenId(nextRefreshTokenId);
        session.setRefreshTokenHash(hashToken(nextRefreshToken));
        session.setRefreshTokenExpiresAt(new Timestamp(jwtTokenProvider.getExpirationFromToken(nextRefreshToken).getTime()));
        session.setLastActivityAt(now());
        if (userAgent != null && !userAgent.isBlank())
        {
            session.setUserAgent(limit(userAgent, 255));
        }
        if (clientIp != null && !clientIp.isBlank())
        {
            session.setClientIp(limit(clientIp, 64));
        }
        authSessionRepository.save(session);

        return new AccessTokenResponse(nextAccessToken, nextRefreshToken, sessionId);
    }

    @Override
    @Transactional(readOnly = true)
    public List<UserSessionResponse> listSessions(Long userId, String currentSessionId)
    {
        return authSessionRepository.findAllByUserIdOrderByLastActivityAtDesc(userId).stream()
                .map(session -> toResponse(session, session.getSessionId().equals(currentSessionId)))
                .toList();
    }

    @Override
    @Transactional
    public void revokeSession(Long userId, String sessionId, String reason)
    {
        AuthSession session = authSessionRepository.findBySessionId(sessionId)
                .orElseThrow(() -> new ServiceException("Session not found", ErrorCode.RESOURCE_NOT_FOUND));
        if (!Objects.equals(session.getUserId(), userId))
        {
            throw new ServiceException("Session not found", ErrorCode.RESOURCE_NOT_FOUND);
        }
        revokeSessionInternal(session, reason == null ? REASON_LOGOUT : reason);
    }

    @Override
    @Transactional
    public void revokeOtherSessions(Long userId, String currentSessionId, String reason)
    {
        for (AuthSession session : authSessionRepository.findAllByUserIdOrderByLastActivityAtDesc(userId))
        {
            if (!session.getSessionId().equals(currentSessionId))
            {
                revokeSessionInternal(session, reason == null ? REASON_LOGOUT : reason);
            }
        }
    }

    @Override
    @Transactional
    public void revokeAllSessions(Long userId, String reason)
    {
        for (AuthSession session : authSessionRepository.findAllByUserIdOrderByLastActivityAtDesc(userId))
        {
            revokeSessionInternal(session, reason == null ? REASON_LOGOUT : reason);
        }
    }

    @Override
    @Transactional(readOnly = true)
    public boolean isSessionActive(String sessionId)
    {
        if (sessionId == null || sessionId.isBlank())
        {
            return false;
        }
        return authSessionRepository.findBySessionId(sessionId)
                .map(session -> session.getRevokedAt() == null && session.getRefreshTokenExpiresAt().after(now()))
                .orElse(false);
    }

    private void revokeSessionInternal(AuthSession session, String reason)
    {
        if (session.getRevokedAt() != null)
        {
            return;
        }
        session.setRevokedAt(now());
        session.setRevokedReason(limit(reason, 128));
        session.setLastActivityAt(now());
        authSessionRepository.save(session);
    }

    private UserSessionResponse toResponse(AuthSession session, boolean current)
    {
        UserSessionResponse response = new UserSessionResponse();
        response.setSessionId(session.getSessionId());
        response.setCurrent(current);
        response.setUserAgent(session.getUserAgent());
        response.setClientIp(session.getClientIp());
        response.setCreateTime(session.getCreateTime());
        response.setLastActivityAt(session.getLastActivityAt());
        response.setRefreshTokenExpiresAt(session.getRefreshTokenExpiresAt());
        response.setRevokedAt(session.getRevokedAt());
        response.setRevokedReason(session.getRevokedReason());
        return response;
    }

    private String hashToken(String token)
    {
        try
        {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(token.getBytes(StandardCharsets.UTF_8)));
        }
        catch (NoSuchAlgorithmException e)
        {
            throw new IllegalStateException("SHA-256 is not available", e);
        }
    }

    private Timestamp now()
    {
        return new Timestamp(System.currentTimeMillis());
    }

    private String limit(String value, int maxLength)
    {
        if (value == null)
        {
            return null;
        }
        return value.length() <= maxLength ? value : value.substring(0, maxLength);
    }
}
