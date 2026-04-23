/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 */
package io.pixelsdb.pixels.rover.config;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import io.pixelsdb.pixels.rover.config.common.RequestIdContext;
import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.List;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for {@link RequestIdFilter}.
 *
 * <p>Pins the three-rule fallback shape mandated by {@code backend.md §5}:
 * <ol>
 *   <li>exactly one {@code request_id_missing=true} warning per fallback;</li>
 *   <li>the literal form is {@code missing-<8 hex>} (no UUID regression);</li>
 *   <li>the fallback is never written back onto the response header.</li>
 * </ol></p>
 */
class RequestIdFilterTest
{
    private static final Pattern FALLBACK_RE = Pattern.compile("^missing-[0-9a-f]{8}$");

    private ListAppender<ILoggingEvent> appender;
    private Logger filterLogger;

    @BeforeEach
    void setUp()
    {
        filterLogger = (Logger) LoggerFactory.getLogger(RequestIdFilter.class);
        appender = new ListAppender<>();
        appender.start();
        filterLogger.addAppender(appender);

        RequestIdContext.clear();
        MDC.clear();
    }

    @AfterEach
    void tearDown()
    {
        filterLogger.detachAppender(appender);
        appender.stop();
        RequestIdContext.clear();
        MDC.clear();
    }

    @Test
    void fallbackShape_is_missingPrefixPlus8Hex()
    {
        for (int i = 0; i < 32; i++)
        {
            String value = RequestIdFilter.generateFallbackRequestId();
            assertTrue(FALLBACK_RE.matcher(value).matches(),
                    "fallback '" + value + "' must match missing-<8 hex>");
        }
    }

    @Test
    void fallbackShape_variesBetweenCalls()
    {
        java.util.Set<String> samples = new java.util.HashSet<>();
        for (int i = 0; i < 32; i++)
        {
            samples.add(RequestIdFilter.generateFallbackRequestId());
        }
        // 32 bits of randomness; 32 samples — duplicates are astronomically unlikely.
        assertEquals(32, samples.size());
    }

    @Test
    void inboundHeader_isPassedThroughUntouched_noWarning() throws Exception
    {
        RequestIdFilter filter = new RequestIdFilter();
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/auth/me");
        request.setRequestURI("/api/v1/auth/me");
        request.addHeader(RequestIdFilter.REQUEST_ID_HEADER, "gw-issued-abc");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        // Single-writer invariant: filter must not write the response header.
        assertNull(response.getHeader(RequestIdFilter.REQUEST_ID_HEADER));

        // No fallback warning.
        List<String> warnings = warningsMatching("request_id_missing=true");
        assertTrue(warnings.isEmpty(), "unexpected warnings: " + warnings);
    }

    @Test
    void missingHeader_generatesFallback_emitsOneWarning_noResponseHeader() throws Exception
    {
        RequestIdFilter filter = new RequestIdFilter();
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/v1/auth/login");
        request.setRequestURI("/api/v1/auth/login");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        // backend.md §5 rule 3: no response header write.
        assertNull(response.getHeader(RequestIdFilter.REQUEST_ID_HEADER));

        // backend.md §5 rule 1: exactly one warning per fallback.
        List<ILoggingEvent> warnings = appender.list.stream()
                .filter(e -> e.getLevel() == Level.WARN)
                .filter(e -> e.getFormattedMessage().contains("request_id_missing=true"))
                .toList();
        assertEquals(1, warnings.size(),
                "expected exactly one fallback warning, got: " + warnings);

        String msg = warnings.get(0).getFormattedMessage();
        assertTrue(msg.contains("route=/api/v1/auth/login"), msg);
        assertTrue(msg.contains("method=POST"), msg);

        // backend.md §5 rule 2: fallback value is missing-<8 hex>, not UUID4.
        int fallbackIdx = msg.indexOf("fallback=");
        assertFalse(fallbackIdx < 0, "fallback= field missing from warning: " + msg);
        String fallback = msg.substring(fallbackIdx + "fallback=".length()).trim();
        assertTrue(FALLBACK_RE.matcher(fallback).matches(),
                "fallback '" + fallback + "' must match missing-<8 hex>");
    }

    @Test
    void emptyHeader_stillTriggersFallback() throws Exception
    {
        RequestIdFilter filter = new RequestIdFilter();
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/health");
        request.setRequestURI("/health");
        request.addHeader(RequestIdFilter.REQUEST_ID_HEADER, "   ");
        MockHttpServletResponse response = new MockHttpServletResponse();
        FilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        List<String> warnings = warningsMatching("request_id_missing=true");
        assertEquals(1, warnings.size(),
                "blank X-Request-Id must be treated as missing: " + warnings);
    }

    @Test
    void contextIsClearedAfterFilterChain() throws Exception
    {
        RequestIdFilter filter = new RequestIdFilter();
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/health");
        request.setRequestURI("/health");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, new MockFilterChain());

        assertNull(RequestIdContext.get(), "RequestIdContext must be cleared");
        assertNull(MDC.get("requestId"), "MDC requestId must be cleared");
    }

    private List<String> warningsMatching(String substring)
    {
        return appender.list.stream()
                .filter(e -> e.getLevel() == Level.WARN)
                .map(ILoggingEvent::getFormattedMessage)
                .filter(m -> m.contains(substring))
                .peek(m -> assertNotNull(m))
                .toList();
    }
}
