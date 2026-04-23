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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.pixelsdb.pixels.rover.config.common.ApiResponse;
import io.pixelsdb.pixels.rover.config.common.ErrorCategory;
import io.pixelsdb.pixels.rover.config.common.ErrorCodeName;
import io.pixelsdb.pixels.rover.constant.HttpStatus;

import java.sql.SQLException;
import java.util.Map;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.transaction.TransactionSystemException;

/**
 * Tests for the C3 degradation-mode contract on the Java side (backend.md §6.7).
 *
 * <p>Ensures:
 * <ol>
 *   <li>Every SQLException-flavored <em>transient</em> failure the handler is
 *       registered for collapses to {@code HTTP 503 + AUTH_DATABASE_UNAVAILABLE +
 *       category=UPSTREAM}.</li>
 *   <li>The narrow allow-list is intentional: integrity violations are NOT
 *       caught here and must fall through to the §6.5 generic 500 handler. This
 *       test documents the boundary so that a PR widening the allow-list shows
 *       up as a visible diff here.</li>
 * </ol>
 */
@DisplayName("GlobalExceptionHandler: C3 degradation-mode contract")
class GlobalExceptionHandlerTest
{
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    @DisplayName(
            "DataAccessResourceFailureException → 503 + AUTH_DATABASE_UNAVAILABLE + UPSTREAM")
    void resourceFailure_mapsTo503()
    {
        ResponseEntity<ApiResponse<?>> resp = handler.handleDatabaseUnavailable(
                new DataAccessResourceFailureException(
                        "Could not open JDBC Connection",
                        new SQLException("connection refused")),
                new MockHttpServletRequest("POST", "/api/v1/auth/login"));

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, resp.getStatusCode().value());
        assertEnvelope(resp);
    }

    @Test
    @DisplayName("CannotCreateTransactionException (pool exhausted) → 503")
    void transactionUnavailable_mapsTo503()
    {
        ResponseEntity<ApiResponse<?>> resp = handler.handleDatabaseUnavailable(
                new CannotCreateTransactionException(
                        "Could not open JDBC Connection for transaction"),
                new MockHttpServletRequest("POST", "/api/v1/auth/login"));

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, resp.getStatusCode().value());
        assertEnvelope(resp);
    }

    @Test
    @DisplayName("TransactionSystemException → 503")
    void transactionSystem_mapsTo503()
    {
        ResponseEntity<ApiResponse<?>> resp = handler.handleDatabaseUnavailable(
                new TransactionSystemException(
                        "Could not commit JDBC transaction"),
                new MockHttpServletRequest("POST", "/api/v1/auth/login"));

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, resp.getStatusCode().value());
        assertEnvelope(resp);
    }

    @Test
    @DisplayName("QueryTimeoutException → 503")
    void queryTimeout_mapsTo503()
    {
        ResponseEntity<ApiResponse<?>> resp = handler.handleDatabaseUnavailable(
                new QueryTimeoutException("statement timeout"),
                new MockHttpServletRequest("POST", "/api/v1/auth/login"));

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, resp.getStatusCode().value());
        assertEnvelope(resp);
    }

    @Test
    @DisplayName("TransientDataAccessException subtype (CannotAcquireLockException) → 503")
    void transientSubtype_mapsTo503()
    {
        TransientDataAccessException transientEx = new CannotAcquireLockException(
                "deadlock detected");

        ResponseEntity<ApiResponse<?>> resp = handler.handleDatabaseUnavailable(
                transientEx,
                new MockHttpServletRequest("POST", "/api/v1/auth/login"));

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, resp.getStatusCode().value());
        assertEnvelope(resp);
    }

    @Test
    @DisplayName(
            "DataIntegrityViolationException NOT caught by the 503 handler "
            + "(documents the narrow allow-list)")
    void integrityViolation_notInAllowlist()
    {
        // Sanity check: the @ExceptionHandler taxonomy on GlobalExceptionHandler
        // lists only transient / resource-failure subtypes; DataIntegrityViolation
        // is not there by design (it is a caller / schema bug and must surface
        // as a §6.5 plain 500 so the bug is investigated rather than absorbed
        // into "DB flaky today" noise).
        //
        // We assert the boundary via the reflection visible to PR review: any
        // future edit that widens the handler to this class shows up as a
        // diff on *this file*, which forces the authors to justify the
        // widening in the PR description.
        java.lang.reflect.Method m;
        try
        {
            m = GlobalExceptionHandler.class.getMethod(
                    "handleDatabaseUnavailable",
                    org.springframework.dao.DataAccessException.class,
                    jakarta.servlet.http.HttpServletRequest.class);
        }
        catch (NoSuchMethodException e)
        {
            throw new AssertionError(e);
        }
        org.springframework.web.bind.annotation.ExceptionHandler ann =
                m.getAnnotation(
                        org.springframework.web.bind.annotation.ExceptionHandler.class);
        assertNotNull(ann);
        for (Class<? extends Throwable> caught : ann.value())
        {
            assertTrue(!caught.equals(DataIntegrityViolationException.class),
                    "DataIntegrityViolationException must not be in the 503 allow-list");
        }
    }

    private static void assertEnvelope(ResponseEntity<ApiResponse<?>> resp)
    {
        ApiResponse<?> body = resp.getBody();
        assertNotNull(body);
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, body.getCode());
        Object detailsObj = body.getDetails();
        assertNotNull(detailsObj, "details object must be present");
        @SuppressWarnings("unchecked")
        Map<String, Object> details = (Map<String, Object>) detailsObj;
        assertEquals(ErrorCodeName.AUTH_DATABASE_UNAVAILABLE, details.get("errorCode"));
        assertEquals(ErrorCategory.UPSTREAM.name(), details.get("category"));
    }
}
