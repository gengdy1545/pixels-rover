/*
 * Copyright 2024 PixelsDB.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package io.pixelsdb.pixels.rover.config.openapi;

import io.pixelsdb.pixels.rover.api.dto.ApiErrorDetails;
import io.pixelsdb.pixels.rover.api.dto.ApiErrorResponse;
import io.pixelsdb.pixels.rover.config.common.ErrorCodeName;
import io.swagger.v3.core.converter.ModelConverters;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.media.Schema;
import io.swagger.v3.oas.models.media.StringSchema;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springdoc.core.customizers.OpenApiCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.TreeSet;

/**
 * OpenAPI customization for the unified failure envelope.
 *
 * <p>Registers {@link ApiErrorDetails} + {@link ApiErrorResponse} as top-level
 * schema components in {@code /openapi.json} so consumers can enumerate
 * {@code details.errorCode} / {@code details.category} without grepping Java
 * source. Springdoc would normally only emit a schema for a type that
 * appears on a concrete controller method signature; the failure envelope
 * is built as a plain {@code Map<String, Object>} at call sites (see
 * {@link io.pixelsdb.pixels.rover.config.common.ApiResponse#error}), so we
 * register the two DTOs through an {@link OpenApiCustomizer} instead.</p>
 *
 * <p><b>Drift guard.</b> The {@code allowableValues} array on
 * {@link ApiErrorDetails#getErrorCode} is a hand-maintained list because
 * {@link io.swagger.v3.oas.annotations.media.Schema} requires a compile-time
 * constant. A {@link PostConstruct} check cross-verifies that every
 * public-static-final string constant in {@link ErrorCodeName} appears in
 * the {@code allowableValues} list — if the two sides drift, the spring
 * context fails to start, matching the policy used elsewhere
 * ({@code FilterConfig} / {@code CaptchaConfig}). This is the Java mirror
 * of assistant-service's pytest guard in
 * {@code tests/test_openapi_error_envelope.py}.</p>
 */
@Configuration
public class OpenApiErrorSchemaContract
{
    private static final Logger LOGGER =
            LoggerFactory.getLogger(OpenApiErrorSchemaContract.class);

    /**
     * {@code allowableValues} declared on {@link ApiErrorDetails#getErrorCode}.
     * Lifted out as a class constant so the drift guard and the schema
     * customizer share one source of truth.
     */
    static final Set<String> ERROR_CODE_ALLOWED_VALUES = new LinkedHashSet<>(
            Arrays.asList(readErrorCodeAllowableValues()));

    @Bean
    public OpenApiCustomizer apiErrorSchemaCustomizer()
    {
        return openApi -> {
            Components components = openApi.getComponents();
            if (components == null)
            {
                components = new Components();
                openApi.setComponents(components);
            }
            // Ask swagger-core to build schemas for the two DTOs (and any
            // nested types such as ErrorCategory). Merge every produced
            // schema into the OpenAPI components map instead of blindly
            // overwriting so we don't stomp on any schemas that other
            // controllers already registered.
            mergeResolvedSchemas(components, ApiErrorDetails.class);
            mergeResolvedSchemas(components, ApiErrorResponse.class);
        };
    }

    @PostConstruct
    void verifyAllowableValuesMatchErrorCodeName()
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
            try
            {
                fromJava.add((String) f.get(null));
            }
            catch (IllegalAccessException e)
            {
                throw new IllegalStateException(
                        "cannot read ErrorCodeName." + f.getName(), e);
            }
        }

        Set<String> missingFromSchema = new TreeSet<>(fromJava);
        missingFromSchema.removeAll(ERROR_CODE_ALLOWED_VALUES);

        Set<String> extraInSchema = new TreeSet<>(ERROR_CODE_ALLOWED_VALUES);
        extraInSchema.removeAll(fromJava);

        if (!missingFromSchema.isEmpty() || !extraInSchema.isEmpty())
        {
            String msg = "ApiErrorDetails.errorCode allowableValues drift vs "
                    + "ErrorCodeName constants. "
                    + "missing from schema: " + missingFromSchema + "; "
                    + "extra in schema: " + extraInSchema + ". "
                    + "Adjust both sides together (backend.md §6.3).";
            LOGGER.error(msg);
            throw new IllegalStateException(msg);
        }
    }

    private static String[] readErrorCodeAllowableValues()
    {
        try
        {
            Field f = ApiErrorDetails.class.getDeclaredField("errorCode");
            io.swagger.v3.oas.annotations.media.Schema anno =
                    f.getAnnotation(io.swagger.v3.oas.annotations.media.Schema.class);
            if (anno == null)
            {
                throw new IllegalStateException(
                        "ApiErrorDetails.errorCode is missing @Schema");
            }
            return anno.allowableValues();
        }
        catch (NoSuchFieldException e)
        {
            throw new IllegalStateException(
                    "ApiErrorDetails.errorCode field not found", e);
        }
    }

    private static void mergeResolvedSchemas(Components components, Class<?> type)
    {
        @SuppressWarnings("rawtypes")
        java.util.Map<String, Schema> resolved =
                ModelConverters.getInstance().readAll(type);
        resolved.forEach((name, schema) -> {
            // Preserve the explicit `enum` we already set via @Schema
            // allowableValues; swagger-core also populates it, but we double
            // up here in case a future annotation change drops it.
            if (name.equals("ApiErrorDetails"))
            {
                Schema<?> errorCodeProp = (Schema<?>) schema.getProperties().get("errorCode");
                if (errorCodeProp instanceof StringSchema)
                {
                    ((StringSchema) errorCodeProp).setEnum(
                            new java.util.ArrayList<>(ERROR_CODE_ALLOWED_VALUES));
                }
            }
            components.addSchemas(name, schema);
        });
    }
}
