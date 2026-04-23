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
package io.pixelsdb.pixels.rover.config.common;

/**
 * Stable string error codes used as {@code details.errorCode} on failure responses.
 *
 * <p>Naming follows {@code backend.md §6.3}:</p>
 * <ul>
 *   <li>Business-domain prefix {@code AUTH_*} for errors originating in this service.</li>
 *   <li>Infrastructure prefix {@code GATEWAY_*} / {@code INTERNAL_*} for access-plane faults
 *       (registered in {@code backend.md §6.3.1}); these are intentionally written via
 *       call sites with known semantics (filters, internal auth), not inferred from HTTP codes.</li>
 * </ul>
 *
 * <p>The legacy {@code fromCode(int)} reverse-lookup table has been removed together with the
 * top-level {@code errorCode} field on {@link ApiResponse}; every failure response now writes
 * {@code errorCode} directly at the call site via
 * {@link ApiResponse#error(int, String, String, ErrorCategory)}.</p>
 */
public final class ErrorCodeName
{
    // ---- Infrastructure prefix (backend.md §6.3.1) ----
    public static final String GATEWAY_IDENTITY_MISSING = "GATEWAY_IDENTITY_MISSING";
    public static final String INTERNAL_AUTH_FAILED = "INTERNAL_AUTH_FAILED";

    // ---- Business-domain prefix AUTH_* (backend.md §6.3) ----

    /** Generic input validation failure (missing field, format, length, ...). */
    public static final String AUTH_INVALID_ARGUMENT = "AUTH_INVALID_ARGUMENT";

    /** Required request parameter (query / form) is missing. */
    public static final String AUTH_MISSING_PARAMETER = "AUTH_MISSING_PARAMETER";

    /** Required request header is missing (non-identity header). */
    public static final String AUTH_MISSING_HEADER = "AUTH_MISSING_HEADER";

    /** Login credentials do not match any user. */
    public static final String AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS";

    /** Refresh token is invalid, expired, or its session has been revoked. */
    public static final String AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN";

    /** JWT type claim is not {@code refresh}. */
    public static final String AUTH_INVALID_TOKEN_TYPE = "AUTH_INVALID_TOKEN_TYPE";

    /** {@code POST /api/v1/auth/refresh} called without a refresh-token cookie. */
    public static final String AUTH_REFRESH_TOKEN_MISSING = "AUTH_REFRESH_TOKEN_MISSING";

    /** Refresh token reuse detected (indicates possible theft; session chain is revoked). */
    public static final String AUTH_REFRESH_TOKEN_REUSED = "AUTH_REFRESH_TOKEN_REUSED";

    /** The session referenced by the request has been revoked or expired. */
    public static final String AUTH_SESSION_REVOKED = "AUTH_SESSION_REVOKED";

    /** The referenced session does not exist. */
    public static final String AUTH_SESSION_NOT_FOUND = "AUTH_SESSION_NOT_FOUND";

    /** The referenced user does not exist. */
    public static final String AUTH_USER_NOT_FOUND = "AUTH_USER_NOT_FOUND";

    /** Attempted to register an already-existing user. */
    public static final String AUTH_USER_ALREADY_EXISTS = "AUTH_USER_ALREADY_EXISTS";

    /** Captcha code provided does not match or has expired. */
    public static final String AUTH_CAPTCHA_INVALID = "AUTH_CAPTCHA_INVALID";

    /** Captcha generation failed (e.g. image encoding error); surfaces as 500. */
    public static final String AUTH_CAPTCHA_GENERATION_FAILED = "AUTH_CAPTCHA_GENERATION_FAILED";

    /** Authorization denied for the requested resource (Spring {@code AccessDeniedException}). */
    public static final String AUTH_ACCESS_DENIED = "AUTH_ACCESS_DENIED";

    /** HTTP method not allowed on the resolved route. */
    public static final String AUTH_METHOD_NOT_ALLOWED = "AUTH_METHOD_NOT_ALLOWED";

    /** Demo / read-only mode rejects the requested write. */
    public static final String AUTH_DEMO_MODE_READONLY = "AUTH_DEMO_MODE_READONLY";

    /** Authenticated principal materialized by Spring Security is not the expected type. */
    public static final String AUTH_INVALID_PRINCIPAL = "AUTH_INVALID_PRINCIPAL";

    private ErrorCodeName()
    {
    }
}
