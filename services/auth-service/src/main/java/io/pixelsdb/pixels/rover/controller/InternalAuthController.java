package io.pixelsdb.pixels.rover.controller;

import io.pixelsdb.pixels.rover.config.security.JwtTokenProvider;
import io.pixelsdb.pixels.rover.rest.request.AuthIntrospectionRequest;
import io.pixelsdb.pixels.rover.rest.response.AuthIntrospectionResponse;
import io.pixelsdb.pixels.rover.service.AuthSessionService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Date;

@RestController
@RequestMapping("/api/internal/auth")
public class InternalAuthController
{
    private final JwtTokenProvider jwtTokenProvider;
    private final AuthSessionService authSessionService;

    public InternalAuthController(JwtTokenProvider jwtTokenProvider, AuthSessionService authSessionService)
    {
        this.jwtTokenProvider = jwtTokenProvider;
        this.authSessionService = authSessionService;
    }

    @PostMapping("/introspect")
    public AuthIntrospectionResponse introspect(@RequestBody(required = false) AuthIntrospectionRequest request)
    {
        if (request == null || request.getToken() == null || request.getToken().isBlank())
        {
            return AuthIntrospectionResponse.inactive("missing_token");
        }
        if (request.getTokenTypeHint() != null && !"access".equals(request.getTokenTypeHint()))
        {
            return AuthIntrospectionResponse.inactive("unsupported_token_type_hint");
        }

        String token = request.getToken();
        if (!jwtTokenProvider.validateToken(token))
        {
            return AuthIntrospectionResponse.inactive("invalid_token");
        }

        String tokenType = jwtTokenProvider.getTokenType(token);
        if (!"access".equals(tokenType))
        {
            return AuthIntrospectionResponse.inactive("invalid_token_type");
        }

        Long userId = jwtTokenProvider.getUserIdFromToken(token);
        String email = jwtTokenProvider.getUsernameFromToken(token);
        String sessionId = jwtTokenProvider.getSessionIdFromToken(token);
        if (email == null || userId == null || sessionId == null || sessionId.isBlank())
        {
            return AuthIntrospectionResponse.inactive("invalid_token_payload");
        }
        if (!authSessionService.isSessionActive(sessionId))
        {
            return AuthIntrospectionResponse.inactive("session_inactive");
        }

        AuthIntrospectionResponse response = new AuthIntrospectionResponse();
        response.setActive(true);
        response.setSub(email);
        response.setEmail(email);
        response.setUserId(userId);
        response.setSessionId(sessionId);
        Date issuedAt = jwtTokenProvider.getIssuedAtFromToken(token);
        Date expiration = jwtTokenProvider.getExpirationFromToken(token);
        response.setIat(issuedAt == null ? null : issuedAt.toInstant().getEpochSecond());
        response.setExp(expiration == null ? null : expiration.toInstant().getEpochSecond());
        return response;
    }
}
