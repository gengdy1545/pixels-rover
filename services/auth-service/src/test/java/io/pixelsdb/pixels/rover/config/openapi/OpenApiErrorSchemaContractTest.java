/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 */
package io.pixelsdb.pixels.rover.config.openapi;

import io.pixelsdb.pixels.rover.api.dto.ApiErrorDetails;
import io.pixelsdb.pixels.rover.config.common.ErrorCodeName;
import io.swagger.v3.oas.annotations.media.Schema;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.Arrays;
import java.util.Set;
import java.util.TreeSet;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Unit tests for the {@link OpenApiErrorSchemaContract} drift guard.
 *
 * <p>These lock in the "single source of truth for {@code details.errorCode}"
 * rule: the public-static-final {@code AUTH_*} / {@code GATEWAY_*} /
 * {@code INTERNAL_*} string constants in {@link ErrorCodeName} MUST equal
 * the {@code allowableValues} array on {@code ApiErrorDetails.errorCode}.
 * If someone adds a new code to one side without the other, the spring
 * context refuses to start — matching
 * {@code scripts/check-contracts.py::frontend-auth-union-equals-java-source}
 * which guards the TS ⇄ Java direction.</p>
 */
class OpenApiErrorSchemaContractTest
{
    @Test
    void allowableValuesExactlyMatchErrorCodeNameConstants() throws Exception
    {
        Set<String> fromJava = new TreeSet<>();
        for (Field f : ErrorCodeName.class.getDeclaredFields())
        {
            if (!Modifier.isPublic(f.getModifiers())
                    || !Modifier.isStatic(f.getModifiers())
                    || !Modifier.isFinal(f.getModifiers()))
            {
                continue;
            }
            if (f.getType() != String.class)
            {
                continue;
            }
            fromJava.add((String) f.get(null));
        }

        Field errorCodeField = ApiErrorDetails.class.getDeclaredField("errorCode");
        Schema anno = errorCodeField.getAnnotation(Schema.class);
        assertNotNull(anno, "ApiErrorDetails.errorCode must carry @Schema");
        Set<String> fromSchema = new TreeSet<>(Arrays.asList(anno.allowableValues()));

        assertEquals(fromJava, fromSchema,
                "ApiErrorDetails.errorCode allowableValues must be an exact "
                        + "permutation of ErrorCodeName's public-static-final "
                        + "constants. Drift detected — adjust both sides "
                        + "together (backend.md §6.3).");
    }

    @Test
    void allowableValuesIncludeAuthInvalidTokenPair()
    {
        // §9.3 condition 8 explicitly calls out AUTH_INVALID_TOKEN / AUTH_INVALID_TOKEN_TYPE
        // as needing explicit registration; pin both here so a future lean-up
        // that collapses them can't silently drop the discoverability surface.
        assertTrue(
                OpenApiErrorSchemaContract.ERROR_CODE_ALLOWED_VALUES.contains(
                        ErrorCodeName.AUTH_INVALID_TOKEN),
                "AUTH_INVALID_TOKEN must be present in ApiErrorDetails.errorCode");
        assertTrue(
                OpenApiErrorSchemaContract.ERROR_CODE_ALLOWED_VALUES.contains(
                        ErrorCodeName.AUTH_INVALID_TOKEN_TYPE),
                "AUTH_INVALID_TOKEN_TYPE must be present in ApiErrorDetails.errorCode");
    }

    @Test
    void driftGuardPassesWhenInSync()
    {
        OpenApiErrorSchemaContract contract = new OpenApiErrorSchemaContract();
        assertDoesNotThrow(contract::verifyAllowableValuesMatchErrorCodeName);
    }
}
