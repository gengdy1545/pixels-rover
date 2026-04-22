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
import java.util.HashMap;
import java.util.Map;

/**
 * Unified API response wrapper aligned with {@code backend.md §6.0}.
 *
 * <p>Success responses only carry {@code data}; failure responses only carry {@code details}.
 * The top-level {@code code} equals the HTTP status code. {@code details.errorCode} is the
 * SCREAMING_SNAKE_CASE business/infra error identifier.</p>
 *
 * <p>Note: {@code errorCode} and {@code apiVersion} top-level fields are retained as
 * transitional shims while the §9 envelope refactor (`todolist.md §9`) is in flight; new
 * call sites should use {@link #errorWithCode(int, String, String)} which sets
 * {@code details.errorCode} directly.</p>
 *
 * @param <T> the type of the data payload
 * @author pixels
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ApiResponse<T> implements Serializable
{
    private static final long serialVersionUID = 1L;

    /** HTTP-equivalent status code. */
    private int code;

    /** Response message (human-readable, do not leak internals). */
    private String message;

    /** Success payload; must be null when {@code details} is set. */
    private T data;

    /** Failure payload; must be null when {@code data} is set. */
    private Map<String, Object> details;

    /** Legacy top-level errorCode mirror; scheduled for removal when §9 lands. */
    private String errorCode;

    /** Request trace id. */
    private String requestId;

    /** Legacy apiVersion mirror; scheduled for removal when §9 lands. */
    private String apiVersion = "v1";

    public ApiResponse()
    {
    }

    public ApiResponse(int code, String message)
    {
        this.code = code;
        this.message = message;
        this.errorCode = ErrorCodeName.fromCode(code);
        this.requestId = RequestIdContext.get();
        this.apiVersion = "v1";
    }

    public ApiResponse(int code, String message, T data)
    {
        this.code = code;
        this.message = message;
        this.data = data;
        this.errorCode = ErrorCodeName.fromCode(code);
        this.requestId = RequestIdContext.get();
        this.apiVersion = "v1";
    }

    // --- Static factory methods ---

    public static <T> ApiResponse<T> success()
    {
        return new ApiResponse<>(HttpStatus.SUCCESS, "success");
    }

    public static <T> ApiResponse<T> success(T data)
    {
        return new ApiResponse<>(HttpStatus.SUCCESS, "success", data);
    }

    public static <T> ApiResponse<T> success(String message, T data)
    {
        return new ApiResponse<>(HttpStatus.SUCCESS, message, data);
    }

    public static <T> ApiResponse<T> error(String message)
    {
        return new ApiResponse<>(HttpStatus.ERROR, message);
    }

    public static <T> ApiResponse<T> error(int code, String message)
    {
        return new ApiResponse<>(code, message);
    }

    /**
     * Build an error response with an explicit SCREAMING_SNAKE_CASE {@code errorCode} written to
     * {@code details.errorCode}. This is the target-state factory per {@code backend.md §6.3}.
     */
    public static <T> ApiResponse<T> errorWithCode(int httpStatus, String message, String errorCode)
    {
        ApiResponse<T> r = new ApiResponse<>(httpStatus, message);
        r.errorCode = errorCode;
        Map<String, Object> d = new HashMap<>();
        d.put("errorCode", errorCode);
        r.details = d;
        return r;
    }

    public static <T> ApiResponse<T> unauthorized(String message)
    {
        return new ApiResponse<>(HttpStatus.UNAUTHORIZED, message);
    }

    public static <T> ApiResponse<T> forbidden(String message)
    {
        return new ApiResponse<>(HttpStatus.FORBIDDEN, message);
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

    public String getRequestId()
    {
        return requestId;
    }

    public void setRequestId(String requestId)
    {
        this.requestId = requestId;
    }

    public String getErrorCode()
    {
        return errorCode;
    }

    public void setErrorCode(String errorCode)
    {
        this.errorCode = errorCode;
    }

    public String getApiVersion()
    {
        return apiVersion;
    }

    public void setApiVersion(String apiVersion)
    {
        this.apiVersion = apiVersion;
    }

    public Map<String, Object> getDetails()
    {
        return details;
    }

    public void setDetails(Map<String, Object> details)
    {
        this.details = details;
    }
}
