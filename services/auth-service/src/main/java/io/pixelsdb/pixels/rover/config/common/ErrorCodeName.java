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

import io.pixelsdb.pixels.rover.constant.ErrorCode;
import io.pixelsdb.pixels.rover.constant.HttpStatus;

/**
 * Stable string error codes shared across services.
 */
public final class ErrorCodeName
{
    public static final String INVALID_ARGUMENT = "INVALID_ARGUMENT";
    public static final String AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED";
    public static final String INVALID_CREDENTIALS = "INVALID_CREDENTIALS";
    public static final String INVALID_TOKEN = "INVALID_TOKEN";
    public static final String INVALID_TOKEN_TYPE = "INVALID_TOKEN_TYPE";
    public static final String ACCESS_DENIED = "ACCESS_DENIED";
    public static final String RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND";
    public static final String RESOURCE_CONFLICT = "RESOURCE_CONFLICT";
    public static final String METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED";
    public static final String DEPENDENCY_ERROR = "DEPENDENCY_ERROR";
    public static final String INTERNAL_ERROR = "INTERNAL_ERROR";

    // Infrastructure-namespace errorCodes (see backend.md §6.3.1 registry).
    // These are intentionally NOT mapped in fromCode(); they are written via
    // ApiResponse.errorWithCode(...) at specific code paths (filters, internal
    // auth) where the access-plane semantics are known.
    public static final String GATEWAY_IDENTITY_MISSING = "GATEWAY_IDENTITY_MISSING";
    public static final String INTERNAL_AUTH_FAILED = "INTERNAL_AUTH_FAILED";

    private ErrorCodeName()
    {
    }

    public static String fromCode(int code)
    {
        if (code == ErrorCode.INVALID_ARGUMENT || code == HttpStatus.BAD_REQUEST)
        {
            return INVALID_ARGUMENT;
        }
        if (code == ErrorCode.AUTHENTICATION_REQUIRED || code == HttpStatus.UNAUTHORIZED)
        {
            return AUTHENTICATION_REQUIRED;
        }
        if (code == ErrorCode.INVALID_CREDENTIALS)
        {
            return INVALID_CREDENTIALS;
        }
        if (code == ErrorCode.INVALID_TOKEN)
        {
            return INVALID_TOKEN;
        }
        if (code == ErrorCode.INVALID_TOKEN_TYPE)
        {
            return INVALID_TOKEN_TYPE;
        }
        if (code == ErrorCode.ACCESS_DENIED || code == HttpStatus.FORBIDDEN)
        {
            return ACCESS_DENIED;
        }
        if (code == ErrorCode.RESOURCE_NOT_FOUND || code == HttpStatus.NOT_FOUND)
        {
            return RESOURCE_NOT_FOUND;
        }
        if (code == ErrorCode.RESOURCE_CONFLICT || code == HttpStatus.CONFLICT)
        {
            return RESOURCE_CONFLICT;
        }
        if (code == HttpStatus.BAD_METHOD)
        {
            return METHOD_NOT_ALLOWED;
        }
        if (code == ErrorCode.DEPENDENCY_ERROR)
        {
            return DEPENDENCY_ERROR;
        }
        if (code == ErrorCode.INTERNAL_ERROR || code == HttpStatus.ERROR)
        {
            return INTERNAL_ERROR;
        }
        return null;
    }
}
