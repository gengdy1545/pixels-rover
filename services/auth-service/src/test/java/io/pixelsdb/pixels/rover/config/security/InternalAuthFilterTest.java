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
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * Unit tests for {@link InternalAuthFilter}.
 *
 * <p>Contract source: {@code backend.md §8.6}. Specifically verifies that the filter scope
 * covers the entire {@code /api/internal/**} prefix (not just {@code introspect}) and that
 * secret failure maps to HTTP 500 + {@code INTERNAL_AUTH_FAILED}.</p>
 */
class InternalAuthFilterTest
{
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final String SECRET = "test-secret";

    @Test
    void externalRouteShouldBypass() throws Exception
    {
        InternalAuthFilter filter = new InternalAuthFilter(SECRET);
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/v1/auth/login");
        request.setRequestURI("/api/v1/auth/login");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
        assertEquals(200, response.getStatus());
    }

    @Test
    void introspectWithValidSecretShouldProceed() throws Exception
    {
        InternalAuthFilter filter = new InternalAuthFilter(SECRET);
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/internal/auth/introspect");
        request.setRequestURI("/api/internal/auth/introspect");
        request.addHeader(InternalAuthFilter.INTERNAL_AUTH_HEADER, SECRET);
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
        assertEquals(200, response.getStatus());
    }

    @Test
    void futureInternalRouteShouldStillBeGuarded() throws Exception
    {
        InternalAuthFilter filter = new InternalAuthFilter(SECRET);
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/internal/audit/flush");
        request.setRequestURI("/api/internal/audit/flush");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = mock(FilterChain.class);

        filter.doFilter(request, response, chain);

        verify(chain, never()).doFilter(request, response);
        assertEquals(500, response.getStatus());
        JsonNode body = OBJECT_MAPPER.readTree(response.getContentAsString());
        assertEquals("INTERNAL_AUTH_FAILED", body.path("details").path("errorCode").asText());
    }

    @Test
    void missingSharedSecretConfigShouldRejectAllInternalTraffic() throws Exception
    {
        InternalAuthFilter filter = new InternalAuthFilter("");
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/internal/auth/introspect");
        request.setRequestURI("/api/internal/auth/introspect");
        request.addHeader(InternalAuthFilter.INTERNAL_AUTH_HEADER, "anything");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertEquals(500, response.getStatus());
        JsonNode body = OBJECT_MAPPER.readTree(response.getContentAsString());
        assertEquals("INTERNAL_AUTH_FAILED", body.path("details").path("errorCode").asText());
    }

    @Test
    void mismatchedSecretShouldReturnInternalAuthFailed() throws Exception
    {
        InternalAuthFilter filter = new InternalAuthFilter(SECRET);
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/internal/auth/introspect");
        request.setRequestURI("/api/internal/auth/introspect");
        request.addHeader(InternalAuthFilter.INTERNAL_AUTH_HEADER, "wrong-secret");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertEquals(500, response.getStatus());
        JsonNode body = OBJECT_MAPPER.readTree(response.getContentAsString());
        assertEquals("INTERNAL_AUTH_FAILED", body.path("details").path("errorCode").asText());
    }
}
