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

import io.pixelsdb.pixels.rover.config.common.ErrorCategory;
import io.swagger.v3.oas.annotations.media.Schema;

/**
 * OpenAPI view of the ``details`` object carried by every non-2xx response.
 *
 * <p>This DTO exists <b>only</b> to surface the failure-envelope shape in
 * {@code /openapi.json} via springdoc (and its downstream callers: the
 * frontend dispatcher, future SDK codegen, API docs portals). It is never
 * instantiated or returned at a controller call site — failure responses
 * are still built by
 * {@link io.pixelsdb.pixels.rover.config.common.ApiResponse#error}, which
 * produces a plain {@code Map<String, Object>} so that call sites can
 * forward arbitrary contextual keys ({@code hint}, {@code field}, ...)
 * without per-field DTO churn.</p>
 *
 * <p><b>Enum values.</b> The {@code errorCode} {@code allowableValues} list
 * MUST include every stable business- / infra-prefix code this service can
 * emit. {@link ErrorCategory} is a first-class Java enum, so springdoc will
 * inline its values from the type itself. If you add a new constant to
 * {@link io.pixelsdb.pixels.rover.config.common.ErrorCodeName}, append it
 * here and ensure {@link
 * io.pixelsdb.pixels.rover.config.openapi.OpenApiErrorSchemaContract}'s
 * startup check lists it too — that guard fails the context load if the
 * two sides drift.</p>
 */
@Schema(
        name = "ApiErrorDetails",
        description =
                "Structured failure details per backend.md §6.0. Present on "
                + "every non-2xx response except the §6.5 "
                + "wholly-unknown-exception safety-net.")
public final class ApiErrorDetails
{
    @Schema(
            description =
                    "Stable SCREAMING_SNAKE_CASE identifier for the failure. "
                    + "Business prefixes (AUTH_*) are owned by this service; "
                    + "infrastructure prefixes (GATEWAY_* / INTERNAL_*) are "
                    + "injected by the gateway or the service-to-service "
                    + "auth filter and are reported for traceability.",
            requiredMode = Schema.RequiredMode.REQUIRED,
            allowableValues = {
                    // ---- Infrastructure prefix (backend.md §6.3.1) ----
                    // Kept in sync with services/auth-service/.../config/common/
                    // ErrorCodeName.java. The spring context refuses to start
                    // if the two sides drift — see OpenApiErrorSchemaContract.
                    "GATEWAY_IDENTITY_MISSING",
                    "INTERNAL_AUTH_FAILED",
                    // ---- Business-domain prefix AUTH_* (backend.md §6.3) ----
                    "AUTH_ACCESS_DENIED",
                    "AUTH_CAPTCHA_GENERATION_FAILED",
                    "AUTH_CAPTCHA_INVALID",
                    "AUTH_DATABASE_UNAVAILABLE",
                    "AUTH_DEMO_MODE_READONLY",
                    "AUTH_INVALID_ARGUMENT",
                    "AUTH_INVALID_CREDENTIALS",
                    "AUTH_INVALID_PRINCIPAL",
                    "AUTH_INVALID_TOKEN",
                    "AUTH_INVALID_TOKEN_TYPE",
                    "AUTH_METHOD_NOT_ALLOWED",
                    "AUTH_MISSING_HEADER",
                    "AUTH_MISSING_PARAMETER",
                    "AUTH_REFRESH_TOKEN_MISSING",
                    "AUTH_REFRESH_TOKEN_REUSED",
                    "AUTH_SESSION_NOT_FOUND",
                    "AUTH_SESSION_REVOKED",
                    "AUTH_USER_ALREADY_EXISTS",
                    "AUTH_USER_NOT_FOUND",
            },
            example = "AUTH_INVALID_CREDENTIALS")
    private String errorCode;

    @Schema(
            description =
                    "Coarse failure category used by the frontend's fall-back "
                    + "dispatcher (backend.md §6.3.2 step 2) when the exact "
                    + "errorCode is not yet recognized.",
            requiredMode = Schema.RequiredMode.REQUIRED,
            implementation = ErrorCategory.class)
    private ErrorCategory category;

    public String getErrorCode()
    {
        return errorCode;
    }

    public void setErrorCode(String errorCode)
    {
        this.errorCode = errorCode;
    }

    public ErrorCategory getCategory()
    {
        return category;
    }

    public void setCategory(ErrorCategory category)
    {
        this.category = category;
    }
}
