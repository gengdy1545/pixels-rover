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
import io.pixelsdb.pixels.rover.config.common.ErrorCategory;
import io.pixelsdb.pixels.rover.config.common.ErrorCodeName;
import io.pixelsdb.pixels.rover.config.security.IdentityHeaderValidationFilter;
import io.pixelsdb.pixels.rover.constant.HttpStatus;
import io.pixelsdb.pixels.rover.exception.CaptchaException;
import io.pixelsdb.pixels.rover.exception.DemoModeException;
import io.pixelsdb.pixels.rover.exception.ServiceException;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.validation.BindException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/**
 * Global exception handler producing the unified {@link ApiResponse} envelope per
 * {@code backend.md §6.0 / §6.3}.
 *
 * <p>Every {@code @ExceptionHandler} method writes {@code details.errorCode} +
 * {@code details.category} at the call site; only the wholly-unknown unhandled exception
 * handler (§6.5) emits a body without {@code details} and logs at {@code level=error} to keep
 * the failure traceable.</p>
 *
 * @author pixels
 */
@RestControllerAdvice
public class GlobalExceptionHandler
{
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /**
     * Handle access denied exception. Gateway normally traps this before auth-service sees it
     * (see {@code gateway.md §6.4}); the server-local 403 is a safety-net so a leaked
     * {@code AccessDeniedException} never surfaces to the client as HTTP 200.
     */
    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<ApiResponse<?>> handleAccessDeniedException(AccessDeniedException e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', permission check failed: '{}'", requestURI, e.getMessage());
        return ResponseEntity.status(HttpStatus.FORBIDDEN).body(
                ApiResponse.error(HttpStatus.FORBIDDEN,
                        "No permission, please contact the administrator",
                        ErrorCodeName.AUTH_ACCESS_DENIED,
                        ErrorCategory.AUTH));
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiResponse<?>> handleHttpRequestMethodNotSupported(HttpRequestMethodNotSupportedException e,
                                                                               HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', HTTP method '{}' is not supported", requestURI, e.getMethod());
        return ResponseEntity.status(HttpStatus.BAD_METHOD).body(
                ApiResponse.error(HttpStatus.BAD_METHOD, e.getMessage(),
                        ErrorCodeName.AUTH_METHOD_NOT_ALLOWED,
                        ErrorCategory.USER_INPUT));
    }

    @ExceptionHandler(CaptchaException.class)
    public ResponseEntity<ApiResponse<?>> handleCaptcha(CaptchaException e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', captcha error: '{}'", requestURI, e.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(
                ApiResponse.error(HttpStatus.BAD_REQUEST, e.getMessage(),
                        ErrorCodeName.AUTH_CAPTCHA_INVALID,
                        ErrorCategory.USER_INPUT));
    }

    /**
     * Handle business exceptions. The {@link ServiceException} itself carries
     * {@code httpStatus} / {@code errorCode} / {@code category}; we just read them back.
     */
    @ExceptionHandler(ServiceException.class)
    public ResponseEntity<ApiResponse<?>> handleServiceException(ServiceException e, HttpServletRequest request)
    {
        log.error(e.getMessage(), e);
        return ResponseEntity.status(e.getHttpStatus()).body(
                ApiResponse.error(e.getHttpStatus(), e.getMessage(),
                        e.getErrorCode(), e.getCategory()));
    }

    /**
     * §6.5 safety-net: wholly-unknown unhandled runtime exception. Body omits {@code details}
     * and the accompanying log line is {@code level=error} to keep the failure investigable.
     */
    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<ApiResponse<?>> handleRuntimeException(RuntimeException e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', unknown runtime exception", requestURI, e);
        return ResponseEntity.status(HttpStatus.ERROR).body(
                ApiResponse.unknownError(HttpStatus.ERROR, "Internal server error"));
    }

    /**
     * §6.5 safety-net for checked exceptions — same shape as {@link #handleRuntimeException}.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<?>> handleException(Exception e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', system exception", requestURI, e);
        return ResponseEntity.status(HttpStatus.ERROR).body(
                ApiResponse.unknownError(HttpStatus.ERROR, "Internal server error"));
    }

    @ExceptionHandler(BindException.class)
    public ResponseEntity<ApiResponse<?>> handleBindException(BindException e)
    {
        log.error(e.getMessage(), e);
        String message = e.getAllErrors().get(0).getDefaultMessage();
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(
                ApiResponse.error(HttpStatus.BAD_REQUEST, message,
                        ErrorCodeName.AUTH_INVALID_ARGUMENT,
                        ErrorCategory.USER_INPUT));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<?>> handleMethodArgumentNotValidException(MethodArgumentNotValidException e)
    {
        log.error(e.getMessage(), e);
        String message = e.getBindingResult().getFieldError().getDefaultMessage();
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(
                ApiResponse.error(HttpStatus.BAD_REQUEST, message,
                        ErrorCodeName.AUTH_INVALID_ARGUMENT,
                        ErrorCategory.USER_INPUT));
    }

    @ExceptionHandler(DemoModeException.class)
    public ResponseEntity<ApiResponse<?>> handleDemoModeException(DemoModeException e)
    {
        return ResponseEntity.status(HttpStatus.FORBIDDEN).body(
                ApiResponse.error(HttpStatus.FORBIDDEN,
                        "Demo mode, operation is not permitted",
                        ErrorCodeName.AUTH_DEMO_MODE_READONLY,
                        ErrorCategory.AUTH));
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<ApiResponse<?>> handleMissingServletRequestParameterException(
            MissingServletRequestParameterException e, HttpServletRequest request)
    {
        String requestURI = request.getRequestURI();
        log.error("Request URI '{}', missing parameter: '{}'", requestURI, e.getParameterName());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(
                ApiResponse.error(HttpStatus.BAD_REQUEST,
                        "Missing required parameter: " + e.getParameterName(),
                        ErrorCodeName.AUTH_MISSING_PARAMETER,
                        ErrorCategory.USER_INPUT));
    }

    /**
     * Handle missing request header exception — defense-in-depth for the gateway identity
     * contract (see {@code backend.md §3.3}).
     *
     * <p>Under normal operation, {@link IdentityHeaderValidationFilter} rejects protected
     * routes whose {@code X-Auth-User-Id} is missing before reaching the controller. This
     * handler exists to cover the residual case where a controller declares another
     * required header or the filter matrix drifts; identity-related headers are still
     * mapped to {@code GATEWAY_IDENTITY_MISSING} so the client-facing contract stays stable.</p>
     */
    @ExceptionHandler(MissingRequestHeaderException.class)
    public ResponseEntity<ApiResponse<?>> handleMissingRequestHeader(
            MissingRequestHeaderException e, HttpServletRequest request)
    {
        String headerName = e.getHeaderName();
        String requestURI = request.getRequestURI();
        if (IdentityHeaderValidationFilter.USER_ID_HEADER.equalsIgnoreCase(headerName))
        {
            log.error("Request URI '{}', gateway identity header missing: '{}'", requestURI, headerName);
            return ResponseEntity.status(HttpStatus.ERROR).body(
                    ApiResponse.error(HttpStatus.ERROR,
                            "Gateway identity header is missing",
                            ErrorCodeName.GATEWAY_IDENTITY_MISSING,
                            ErrorCategory.INTERNAL));
        }
        log.error("Request URI '{}', missing request header: '{}'", requestURI, headerName);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(
                ApiResponse.error(HttpStatus.BAD_REQUEST,
                        "Missing required header: " + headerName,
                        ErrorCodeName.AUTH_MISSING_HEADER,
                        ErrorCategory.USER_INPUT));
    }

    /**
     * Handle type-mismatched {@code @RequestHeader} bindings — for example a non-numeric
     * {@code X-Auth-User-Id} value. Per {@code backend.md §3.3} the malformed identity is
     * treated identically to a missing one.
     */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ApiResponse<?>> handleMethodArgumentTypeMismatch(
            MethodArgumentTypeMismatchException e, HttpServletRequest request)
    {
        String paramName = e.getName();
        String requestURI = request.getRequestURI();
        if (IdentityHeaderValidationFilter.USER_ID_HEADER.equalsIgnoreCase(paramName)
                || "userId".equals(paramName))
        {
            log.error("Request URI '{}', gateway identity header has invalid value: '{}'",
                    requestURI, e.getValue());
            return ResponseEntity.status(HttpStatus.ERROR).body(
                    ApiResponse.error(HttpStatus.ERROR,
                            "Gateway identity header is invalid",
                            ErrorCodeName.GATEWAY_IDENTITY_MISSING,
                            ErrorCategory.INTERNAL));
        }
        log.error("Request URI '{}', argument type mismatch: '{}'", requestURI, paramName);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(
                ApiResponse.error(HttpStatus.BAD_REQUEST,
                        "Invalid value for parameter: " + paramName,
                        ErrorCodeName.AUTH_INVALID_ARGUMENT,
                        ErrorCategory.USER_INPUT));
    }
}
