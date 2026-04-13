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

/**
 * Unified API response wrapper.
 *
 * @param <T> the type of the data payload
 * @author pixels
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ApiResponse<T> implements Serializable
{
    private static final long serialVersionUID = 1L;

    /** Status code */
    private int code;

    /** Response message */
    private String message;

    /** Data payload */
    private T data;

    public ApiResponse()
    {
    }

    public ApiResponse(int code, String message)
    {
        this.code = code;
        this.message = message;
    }

    public ApiResponse(int code, String message, T data)
    {
        this.code = code;
        this.message = message;
        this.data = data;
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
}
