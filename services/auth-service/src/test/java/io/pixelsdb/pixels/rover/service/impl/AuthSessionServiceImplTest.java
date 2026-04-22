package io.pixelsdb.pixels.rover.service.impl;

import io.pixelsdb.pixels.rover.config.security.JwtTokenProvider;
import io.pixelsdb.pixels.rover.exception.ServiceException;
import io.pixelsdb.pixels.rover.mapper.AuthSessionRepository;
import io.pixelsdb.pixels.rover.model.AuthSession;
import io.pixelsdb.pixels.rover.rest.response.AccessTokenResponse;
import io.pixelsdb.pixels.rover.rest.response.TokenResponse;
import io.pixelsdb.pixels.rover.rest.response.UserSessionResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.sql.Timestamp;
import java.util.Date;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AuthSessionServiceImplTest
{
    private static final String SECRET = "cGl4ZWxzZGItcm92ZXItand0LXNlY3JldC1rZXktMjAyNC1taW5pbXVtLTI1Ni1iaXRz";

    @Mock
    private AuthSessionRepository authSessionRepository;

    @InjectMocks
    private AuthSessionServiceImpl authSessionService;

    private JwtTokenProvider jwtTokenProvider;

    @BeforeEach
    void setUp()
    {
        jwtTokenProvider = new JwtTokenProvider(
                SECRET,
                "HS256",
                "pixels-rover-auth-service",
                "default-hmac",
                "",
                "",
                "",
                "",
                "",
                3600000L,
                604800000L
        );
        authSessionService = new AuthSessionServiceImpl(jwtTokenProvider, authSessionRepository);
    }

    @Test
    void createSessionShouldPersistSessionAndReturnTokens()
    {
        when(authSessionRepository.save(any(AuthSession.class))).thenAnswer(invocation -> invocation.getArgument(0));

        TokenResponse response = authSessionService.createSession("alice@example.com", 7L, "JUnit", "127.0.0.1");

        assertNotNull(response.getAccessToken());
        assertNotNull(response.getRefreshToken());
        assertNotNull(response.getSessionId());
        assertEquals(response.getSessionId(), jwtTokenProvider.getSessionIdFromToken(response.getAccessToken()));
        assertEquals(response.getSessionId(), jwtTokenProvider.getSessionIdFromToken(response.getRefreshToken()));
        assertNotNull(jwtTokenProvider.getTokenIdFromToken(response.getRefreshToken()));
    }

    @Test
    void refreshSessionShouldRotateRefreshToken()
    {
        when(authSessionRepository.save(any(AuthSession.class))).thenAnswer(invocation -> invocation.getArgument(0));
        TokenResponse initial = authSessionService.createSession("alice@example.com", 7L, "JUnit", "127.0.0.1");

        AuthSession persisted = capturedSession();
        when(authSessionRepository.findBySessionId(initial.getSessionId())).thenReturn(Optional.of(persisted));
        when(authSessionRepository.save(any(AuthSession.class))).thenAnswer(invocation -> invocation.getArgument(0));

        AccessTokenResponse refreshed = authSessionService.refreshSession(initial.getRefreshToken(), "JUnit2", "10.0.0.1");

        assertNotNull(refreshed.getAccessToken());
        assertNotNull(refreshed.getRefreshToken());
        assertEquals(initial.getSessionId(), refreshed.getSessionId());
        assertNotEquals(initial.getRefreshToken(), refreshed.getRefreshToken());
        assertEquals(initial.getSessionId(), jwtTokenProvider.getSessionIdFromToken(refreshed.getRefreshToken()));
    }

    @Test
    void refreshSessionShouldRevokeSessionWhenOldRefreshTokenReused()
    {
        when(authSessionRepository.save(any(AuthSession.class))).thenAnswer(invocation -> invocation.getArgument(0));
        TokenResponse initial = authSessionService.createSession("alice@example.com", 7L, "JUnit", "127.0.0.1");

        AuthSession persisted = capturedSession();
        when(authSessionRepository.findBySessionId(initial.getSessionId())).thenReturn(Optional.of(persisted));
        when(authSessionRepository.save(any(AuthSession.class))).thenAnswer(invocation -> invocation.getArgument(0));

        AccessTokenResponse refreshed = authSessionService.refreshSession(initial.getRefreshToken(), "JUnit2", "10.0.0.1");
        persisted.setRefreshTokenHash("different-hash");
        persisted.setCurrentRefreshTokenId(jwtTokenProvider.getTokenIdFromToken(refreshed.getRefreshToken()));

        ServiceException exception = assertThrows(
                ServiceException.class,
                () -> authSessionService.refreshSession(initial.getRefreshToken(), "JUnit3", "10.0.0.2")
        );

        assertEquals("Refresh token reuse detected", exception.getMessage());
        assertNotNull(persisted.getRevokedAt());
        assertEquals("refresh_token_reuse_detected", persisted.getRevokedReason());
    }

    @Test
    void isSessionActiveShouldRejectRevokedSession()
    {
        AuthSession session = new AuthSession();
        session.setSessionId("session-1");
        session.setRefreshTokenExpiresAt(new Timestamp(new Date().getTime() + 1000));
        session.setRevokedAt(new Timestamp(new Date().getTime()));

        when(authSessionRepository.findBySessionId("session-1")).thenReturn(Optional.of(session));

        assertFalse(authSessionService.isSessionActive("session-1"));
    }

    @Test
    void listSessionsShouldMarkCurrentSession()
    {
        AuthSession session = new AuthSession();
        session.setSessionId("session-1");
        session.setCreateTime(new Timestamp(new Date().getTime()));
        session.setLastActivityAt(new Timestamp(new Date().getTime()));
        session.setRefreshTokenExpiresAt(new Timestamp(new Date().getTime() + 1000));

        when(authSessionRepository.findAllByUserIdOrderByLastActivityAtDesc(7L)).thenReturn(List.of(session));

        List<UserSessionResponse> sessions = authSessionService.listSessions(7L, "session-1");

        assertEquals(1, sessions.size());
        assertTrue(sessions.get(0).isCurrent());
    }

    private AuthSession capturedSession()
    {
        ArgumentCaptor<AuthSession> captor = ArgumentCaptor.forClass(AuthSession.class);
        verify(authSessionRepository).save(captor.capture());
        AuthSession session = captor.getValue();
        if (session.getCreateTime() == null)
        {
            session.onCreate();
        }
        return session;
    }
}
