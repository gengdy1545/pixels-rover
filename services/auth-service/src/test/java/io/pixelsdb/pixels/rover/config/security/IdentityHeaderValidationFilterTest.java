/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 */
package io.pixelsdb.pixels.rover.config.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * Unit tests for {@link IdentityHeaderValidationFilter}.
 *
 * <p>Covers the {@code backend.md §3.3} contract: missing / malformed
 * {@code X-Auth-User-Id} both collapse to HTTP 500 +
 * {@code details.errorCode="GATEWAY_IDENTITY_MISSING"}; valid header populates
 * Spring Security's context with a minimal principal so {@code .authenticated()} passes.</p>
 */
class IdentityHeaderValidationFilterTest
{
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private final IdentityHeaderValidationFilter filter = new IdentityHeaderValidationFilter();

    @AfterEach
    void clearContext()
    {
        SecurityContextHolder.clearContext();
    }

    @Test
    void publicEntryPointShouldBypassFilter() throws Exception
    {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/v1/auth/login");
        request.setRequestURI("/api/v1/auth/login");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
        assertEquals(200, response.getStatus());
    }

    @Test
    void missingHeaderShouldReturn500WithGatewayIdentityMissing() throws Exception
    {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/auth/me");
        request.setRequestURI("/api/v1/auth/me");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain, never()).doFilter(request, response);
        assertEquals(500, response.getStatus());
        JsonNode body = OBJECT_MAPPER.readTree(response.getContentAsString());
        assertEquals("GATEWAY_IDENTITY_MISSING", body.path("details").path("errorCode").asText());
    }

    @Test
    void malformedHeaderShouldReturn500WithGatewayIdentityMissing() throws Exception
    {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/v1/auth/logout");
        request.setRequestURI("/api/v1/auth/logout");
        request.addHeader(IdentityHeaderValidationFilter.USER_ID_HEADER, "not-a-number");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain, never()).doFilter(request, response);
        assertEquals(500, response.getStatus());
        JsonNode body = OBJECT_MAPPER.readTree(response.getContentAsString());
        assertEquals("GATEWAY_IDENTITY_MISSING", body.path("details").path("errorCode").asText());
    }

    @Test
    void negativeUserIdShouldBeTreatedAsMalformed() throws Exception
    {
        MockHttpServletRequest request = new MockHttpServletRequest("DELETE", "/api/v1/auth/sessions/session-1");
        request.setRequestURI("/api/v1/auth/sessions/session-1");
        request.addHeader(IdentityHeaderValidationFilter.USER_ID_HEADER, "-7");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertEquals(500, response.getStatus());
        JsonNode body = OBJECT_MAPPER.readTree(response.getContentAsString());
        assertEquals("GATEWAY_IDENTITY_MISSING", body.path("details").path("errorCode").asText());
    }

    @Test
    void validIdentityShouldPopulateContextAndChain() throws Exception
    {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/auth/me");
        request.setRequestURI("/api/v1/auth/me");
        request.addHeader(IdentityHeaderValidationFilter.USER_ID_HEADER, "42");
        request.addHeader(IdentityHeaderValidationFilter.USER_EMAIL_HEADER, "alice@example.com");
        MockHttpServletResponse response = new MockHttpServletResponse();
        RecordingFilterChain chain = new RecordingFilterChain();

        filter.doFilter(request, response, chain);

        assertTrue(chain.invoked);
        // After the chain returns, the filter clears SecurityContextHolder. We assert the
        // principal was visible during chain execution.
        assertEquals("alice@example.com", chain.principalName);
        assertNull(SecurityContextHolder.getContext().getAuthentication());
        assertEquals(200, response.getStatus());
    }

    @Test
    void sessionsListingShouldBeGuardedByFilter() throws Exception
    {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/auth/sessions");
        request.setRequestURI("/api/v1/auth/sessions");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertEquals(500, response.getStatus());
        assertNotNull(response.getContentAsString());
    }

    private static final class RecordingFilterChain extends MockFilterChain
    {
        boolean invoked;
        String principalName;

        @Override
        public void doFilter(jakarta.servlet.ServletRequest request, jakarta.servlet.ServletResponse response)
        {
            invoked = true;
            principalName = String.valueOf(
                    SecurityContextHolder.getContext().getAuthentication().getPrincipal());
        }
    }
}
