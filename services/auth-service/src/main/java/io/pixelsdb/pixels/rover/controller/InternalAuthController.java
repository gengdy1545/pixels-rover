package io.pixelsdb.pixels.rover.controller;

import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.config.security.JwtTokenProvider;
import io.pixelsdb.pixels.rover.rest.request.AuthIntrospectionRequest;
import io.pixelsdb.pixels.rover.rest.response.AuthIntrospectionResponse;
import io.pixelsdb.pixels.rover.service.AuthSessionService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Date;

/**
 * Internal introspection endpoint consumed by the gateway.
 *
 * <p>Per {@code backend.md §8.6.1}, the response is wrapped in the standard {@link ApiResponse}
 * envelope (no RFC 7662 bare-schema exemption). {@code AuthIntrospectionResponse}'s field set is
 * unchanged — it sits as the {@code data} payload. The gateway ({@code gateway-auth.lua}) reads
 * {@code decoded.data.active / userId / email / sessionId} accordingly. Failure paths (secret
 * mismatch / unexpected exception) flow through {@code GlobalExceptionHandler} and return the
 * same envelope with {@code details.errorCode}.</p>
 *
 * <p>Inactive outcomes ("missing_token", "invalid_token", "session_inactive", ...) are still
 * {@code 200 OK} responses that set {@code data.active=false}; they are not HTTP errors, matching
 * the RFC 7662 token-state semantics while still complying with the unified envelope.</p>
 */
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
    public ApiResponse<AuthIntrospectionResponse> introspect(@RequestBody(required = false) AuthIntrospectionRequest request)
    {
        return ApiResponse.success(buildIntrospection(request));
    }

    private AuthIntrospectionResponse buildIntrospection(AuthIntrospectionRequest request)
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
