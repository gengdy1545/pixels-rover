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
package io.pixelsdb.pixels.rover.config.exception;

import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.constant.HttpStatus;
import io.pixelsdb.pixels.rover.exception.CaptchaException;
import io.pixelsdb.pixels.rover.exception.DemoModeException;
import io.pixelsdb.pixels.rover.exception.ServiceException;
import io.pixelsdb.pixels.rover.utils.StringUtils;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.validation.BindException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Global exception handler that returns unified ApiResponse format.
 *
 * @author pixels
 */
@RestControllerAdvice
public class GlobalExceptionHandler
{
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /**
     * Handle access denied exception.
     */
    @ExceptionHandler(AccessDeniedException.class)
    public ApiResponse<?> handleAccessDeniedException(AccessDeniedException e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', permission check failed: '{}'", requestURI, e.getMessage());
        return ApiResponse.forbidden("No permission, please contact the administrator");
    }

    /**
     * Handle unsupported HTTP method.
     */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ApiResponse<?> handleHttpRequestMethodNotSupported(HttpRequestMethodNotSupportedException e,
                                                              HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', HTTP method '{}' is not supported", requestURI, e.getMethod());
        return ApiResponse.error(HttpStatus.BAD_METHOD, e.getMessage());
    }

    /**
     * Handle captcha exception.
     */
    @ExceptionHandler(CaptchaException.class)
    public ApiResponse<?> handleCaptcha(CaptchaException e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', captcha error: '{}'", requestURI, e.getMessage());
        return ApiResponse.error(HttpStatus.BAD_REQUEST, e.getMessage());
    }

    /**
     * Handle business service exception.
     */
    @ExceptionHandler(ServiceException.class)
    public ApiResponse<?> handleServiceException(ServiceException e, HttpServletRequest request)
    {
        log.error(e.getMessage(), e);
        Integer code = e.getCode();
        return StringUtils.isNotNull(code)
                ? ApiResponse.error(code, e.getMessage())
                : ApiResponse.error(e.getMessage());
    }

    /**
     * Handle unknown runtime exception.
     */
    @ExceptionHandler(RuntimeException.class)
    public ApiResponse<?> handleRuntimeException(RuntimeException e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', unknown runtime exception", requestURI, e);
        return ApiResponse.error(e.getMessage());
    }

    /**
     * Handle generic system exception.
     */
    @ExceptionHandler(Exception.class)
    public ApiResponse<?> handleException(Exception e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', system exception", requestURI, e);
        return ApiResponse.error(e.getMessage());
    }

    /**
     * Handle bean validation bind exception.
     */
    @ExceptionHandler(BindException.class)
    public ApiResponse<?> handleBindException(BindException e)
    {
        log.error(e.getMessage(), e);
        String message = e.getAllErrors().get(0).getDefaultMessage();
        return ApiResponse.error(HttpStatus.BAD_REQUEST, message);
    }

    /**
     * Handle method argument validation exception.
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ApiResponse<?> handleMethodArgumentNotValidException(MethodArgumentNotValidException e)
    {
        log.error(e.getMessage(), e);
        String message = e.getBindingResult().getFieldError().getDefaultMessage();
        return ApiResponse.error(HttpStatus.BAD_REQUEST, message);
    }

    /**
     * Handle demo mode exception.
     */
    @ExceptionHandler(DemoModeException.class)
    public ApiResponse<?> handleDemoModeException(DemoModeException e)
    {
        return ApiResponse.error("Demo mode, operation is not permitted");
    }
}
