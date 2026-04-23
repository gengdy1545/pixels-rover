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

import com.fasterxml.jackson.annotation.JsonInclude;
import io.pixelsdb.pixels.rover.constant.HttpStatus;

import java.io.Serializable;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Unified API response envelope aligned with {@code backend.md §6.0}.
 *
 * <p>Contract:</p>
 * <ul>
 *   <li>Top-level {@code code} strictly equals the HTTP status code; no 5-digit business codes.</li>
 *   <li>Success responses carry {@code data} only; failure responses carry {@code details} only.</li>
 *   <li>Failure responses <strong>must</strong> carry both {@code details.errorCode} (SCREAMING_SNAKE_CASE
 *       business/infra identifier) and {@code details.category} (coarse {@link ErrorCategory} enum).
 *       The only exception is the §6.5 safety-net handler for wholly-unknown unhandled exceptions.</li>
 *   <li>{@code apiVersion} is intentionally absent from the envelope — API versioning is carried by
 *       the URL prefix {@code /api/v1/}.</li>
 * </ul>
 *
 * @param <T> the type of the data payload
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ApiResponse<T> implements Serializable
{
    private static final long serialVersionUID = 2L;

    /** HTTP status code; enforced equal to the ResponseEntity status. */
    private int code;

    /** Human-readable message (do not leak internals; see §6.4). */
    private String message;

    /** Success payload; must be null when {@code details} is set. */
    private T data;

    /** Failure payload; must be null when {@code data} is set. */
    private Map<String, Object> details;

    /** Request trace id (see §5; required on every response). */
    private String requestId;

    public ApiResponse()
    {
    }

    private ApiResponse(int code, String message, T data, Map<String, Object> details)
    {
        this.code = code;
        this.message = message;
        this.data = data;
        this.details = details;
        this.requestId = RequestIdContext.get();
    }

    // --- Success factory methods ---

    public static <T> ApiResponse<T> success()
    {
        return new ApiResponse<>(HttpStatus.SUCCESS, "success", null, null);
    }

    public static <T> ApiResponse<T> success(T data)
    {
        return new ApiResponse<>(HttpStatus.SUCCESS, "success", data, null);
    }

    public static <T> ApiResponse<T> success(String message, T data)
    {
        return new ApiResponse<>(HttpStatus.SUCCESS, message, data, null);
    }

    // --- Failure factory methods ---

    /**
     * Build a failure response with the mandatory {@code details.errorCode} and
     * {@code details.category} per {@code backend.md §6.0}.
     *
     * @param httpStatus HTTP status code (equals the ResponseEntity status and the top-level {@code code})
     * @param message    human-readable message (do not leak internals)
     * @param errorCode  SCREAMING_SNAKE_CASE business/infra identifier (required)
     * @param category   coarse error category for frontend fallback UX (required)
     */
    public static <T> ApiResponse<T> error(int httpStatus, String message, String errorCode,
                                           ErrorCategory category)
    {
        return error(httpStatus, message, errorCode, category, null);
    }

    /**
     * Same as {@link #error(int, String, String, ErrorCategory)} but merges additional keys
     * (for example {@code hint} / {@code field}) into {@code details}.
     */
    public static <T> ApiResponse<T> error(int httpStatus, String message, String errorCode,
                                           ErrorCategory category, Map<String, Object> extras)
    {
        if (errorCode == null || errorCode.isBlank())
        {
            throw new IllegalArgumentException("errorCode is required on failure responses");
        }
        if (category == null)
        {
            throw new IllegalArgumentException("category is required on failure responses");
        }
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("errorCode", errorCode);
        d.put("category", category.name());
        if (extras != null)
        {
            for (Map.Entry<String, Object> entry : extras.entrySet())
            {
                if (!"errorCode".equals(entry.getKey()) && !"category".equals(entry.getKey()))
                {
                    d.put(entry.getKey(), entry.getValue());
                }
            }
        }
        return new ApiResponse<>(httpStatus, message, null, d);
    }

    /**
     * Safety-net factory for the §6.5 wholly-unknown unhandled exception handler — this is the
     * <strong>only</strong> path that may emit a failure response without {@code details}.
     * All other call sites must use {@link #error(int, String, String, ErrorCategory)}.
     */
    public static <T> ApiResponse<T> unknownError(int httpStatus, String message)
    {
        return new ApiResponse<>(httpStatus, message, null, null);
    }

    // --- Getters and Setters ---

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

    public T getData()
    {
        return data;
    }

    public void setData(T data)
    {
        this.data = data;
    }

    public Map<String, Object> getDetails()
    {
        return details;
    }

    public void setDetails(Map<String, Object> details)
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
