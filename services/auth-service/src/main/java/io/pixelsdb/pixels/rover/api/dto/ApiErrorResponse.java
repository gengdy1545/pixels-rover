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
package io.pixelsdb.pixels.rover.api.dto;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * OpenAPI view of the full non-2xx response envelope (backend.md §6.0).
 *
 * <p>Like {@link ApiErrorDetails}, this class is a schema-only DTO — it is
 * never instantiated at a controller call site. Springdoc picks it up via
 * {@link io.pixelsdb.pixels.rover.config.openapi.OpenApiErrorSchemaContract}'s
 * {@code OpenApiCustomizer} bean and publishes it as a top-level
 * {@code components/schemas/ApiErrorResponse} entry so API consumers can
 * discover the shape from the OpenAPI document alone.</p>
 */
@Schema(
        name = "ApiErrorResponse",
        description =
                "The non-2xx response envelope per backend.md §6.0. Top-level "
                + "`code` equals the HTTP status line; `data` is always null "
                + "on failure; `details` is present except for the §6.5 "
                + "safety-net handler for wholly-unknown exceptions.")
public final class ApiErrorResponse
{
    @Schema(
            description =
                    "HTTP status code; strictly equal to the transport status "
                    + "line. Must not carry a 5-digit legacy business code "
                    + "(sunset, backend.md §6.3).",
            requiredMode = Schema.RequiredMode.REQUIRED,
            example = "401")
    private int code;

    @Schema(
            description =
                    "Human-readable short description (do not leak internals).",
            requiredMode = Schema.RequiredMode.REQUIRED,
            example = "Invalid credentials")
    private String message;

    @Schema(
            description =
                    "Structured failure details. Present on every non-2xx "
                    + "response except the §6.5 wholly-unknown-exception "
                    + "safety-net.",
            nullable = true)
    private ApiErrorDetails details;

    @Schema(
            description =
                    "Request trace id; echoed from gateway-injected "
                    + "`X-Request-Id` or a `missing-<8 hex>` fallback when "
                    + "the header is absent (backend.md §5).",
            nullable = true,
            example = "b3c8d1e2-1a2b-4c4d-8e9f-0a1b2c3d4e5f")
    private String requestId;

    public int getCode()
    {
        return code;
    }

    public void setCode(int code)
    {
        this.code = code;
    }

    public String getMessage()
    {
        return message;
    }

    public void setMessage(String message)
    {
        this.message = message;
    }

    public ApiErrorDetails getDetails()
    {
        return details;
    }

    public void setDetails(ApiErrorDetails details)
    {
        this.details = details;
    }

    public String getRequestId()
    {
        return requestId;
    }

    public void setRequestId(String requestId)
    {
        this.requestId = requestId;
    }
}
