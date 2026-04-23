/*
 * Copyright 2023 PixelsDB.
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
package io.pixelsdb.pixels.rover.exception;

import io.pixelsdb.pixels.rover.config.common.ErrorCategory;

/**
 * Business exception whose fields drive the unified {@code ApiResponse} envelope (see
 * {@code backend.md §6.0 / §6.3}).
 *
 * <p>The previous {@code Integer code} field (5-digit business code) has been retired together
 * with the top-level {@code errorCode} on the envelope; call sites now supply the final
 * SCREAMING_SNAKE_CASE {@code errorCode}, the coarse {@link ErrorCategory}, and the HTTP status
 * code directly.</p>
 */
public final class ServiceException extends RuntimeException
{
    private static final long serialVersionUID = 2L;

    private final int httpStatus;
    private final String errorCode;
    private final ErrorCategory category;
    private String message;
    private String detailMessage;

    public ServiceException(int httpStatus, String message, String errorCode, ErrorCategory category)
    {
        this.httpStatus = httpStatus;
        this.message = message;
        this.errorCode = errorCode;
        this.category = category;
    }

    public int getHttpStatus()
    {
        return httpStatus;
    }

    public String getErrorCode()
    {
        return errorCode;
    }

    public ErrorCategory getCategory()
    {
        return category;
    }

    @Override
    public String getMessage()
    {
        return message;
    }

    public ServiceException setMessage(String message)
    {
        this.message = message;
        return this;
    }

    public String getDetailMessage()
    {
        return detailMessage;
    }

    public ServiceException setDetailMessage(String detailMessage)
    {
        this.detailMessage = detailMessage;
        return this;
    }
}
