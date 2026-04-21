package io.pixelsdb.pixels.rover.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.pixelsdb.pixels.rover.config.security.JwtTokenProvider;
import io.pixelsdb.pixels.rover.rest.request.AuthIntrospectionRequest;
import io.pixelsdb.pixels.rover.service.AuthSessionService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.bean.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.Date;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(InternalAuthController.class)
@AutoConfigureMockMvc(addFilters = false)
class InternalAuthControllerTest
{
    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private JwtTokenProvider jwtTokenProvider;

    @MockBean
    private AuthSessionService authSessionService;

    @Test
    void introspectShouldReturnInactiveWhenTokenMissing() throws Exception
    {
        mockMvc.perform(post("/api/internal/auth/introspect")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.active").value(false))
                .andExpect(jsonPath("$.reason").value("missing_token"));
    }

    @Test
    void introspectShouldReturnInactiveForRefreshToken() throws Exception
    {
        AuthIntrospectionRequest request = new AuthIntrospectionRequest();
        request.setToken("refresh-token");
        request.setTokenTypeHint("access");

        when(jwtTokenProvider.validateToken("refresh-token")).thenReturn(true);
        when(jwtTokenProvider.getTokenType("refresh-token")).thenReturn("refresh");

        mockMvc.perform(post("/api/internal/auth/introspect")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.active").value(false))
                .andExpect(jsonPath("$.reason").value("invalid_token_type"));
    }

    @Test
    void introspectShouldReturnActiveForValidAccessToken() throws Exception
    {
        AuthIntrospectionRequest request = new AuthIntrospectionRequest();
        request.setToken("access-token");
        request.setTokenTypeHint("access");

        Date issuedAt = Date.from(Instant.ofEpochSecond(1_710_000_000L));
        Date expiration = Date.from(Instant.ofEpochSecond(1_710_003_600L));

        when(jwtTokenProvider.validateToken("access-token")).thenReturn(true);
        when(jwtTokenProvider.getTokenType("access-token")).thenReturn("access");
        when(jwtTokenProvider.getUserIdFromToken("access-token")).thenReturn(7L);
        when(jwtTokenProvider.getUsernameFromToken("access-token")).thenReturn("alice@example.com");
        when(jwtTokenProvider.getSessionIdFromToken("access-token")).thenReturn("session-7");
        when(jwtTokenProvider.getIssuedAtFromToken("access-token")).thenReturn(issuedAt);
        when(jwtTokenProvider.getExpirationFromToken("access-token")).thenReturn(expiration);
        when(authSessionService.isSessionActive("session-7")).thenReturn(true);

        mockMvc.perform(post("/api/internal/auth/introspect")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.active").value(true))
                .andExpect(jsonPath("$.sub").value("alice@example.com"))
                .andExpect(jsonPath("$.email").value("alice@example.com"))
                .andExpect(jsonPath("$.userId").value(7))
                .andExpect(jsonPath("$.sessionId").value("session-7"))
                .andExpect(jsonPath("$.iat").value(1_710_000_000L))
                .andExpect(jsonPath("$.exp").value(1_710_003_600L));
    }

    @Test
    void introspectShouldReturnInactiveWhenSessionIdMissing() throws Exception
    {
        AuthIntrospectionRequest request = new AuthIntrospectionRequest();
        request.setToken("access-token-without-session");
        request.setTokenTypeHint("access");

        when(jwtTokenProvider.validateToken("access-token-without-session")).thenReturn(true);
        when(jwtTokenProvider.getTokenType("access-token-without-session")).thenReturn("access");
        when(jwtTokenProvider.getUserIdFromToken("access-token-without-session")).thenReturn(7L);
        when(jwtTokenProvider.getUsernameFromToken("access-token-without-session")).thenReturn("alice@example.com");
        when(jwtTokenProvider.getSessionIdFromToken("access-token-without-session")).thenReturn(null);

        mockMvc.perform(post("/api/internal/auth/introspect")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.active").value(false))
                .andExpect(jsonPath("$.reason").value("invalid_token_payload"));
    }
}
