import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { AxiosRequestConfig } from 'axios';
import type { ApiErrorResponse, ApiSuccessResponse } from '../types/common';
import { ensureRequestId } from '../storage/requestId';
import { getCookie } from '../storage/cookie';
import { redirectToLogin } from '../storage/navigation';
import { ApiError, apiErrorFromEnvelope } from './apiError';

// ════════════════════════════════════════
// Axios instance
// ════════════════════════════════════════

const httpClient = axios.create({
  baseURL: '',
  timeout: 30000,
  withCredentials: true, // Always send cookies with requests
  headers: {
    'Content-Type': 'application/json',
  },
});

// ════════════════════════════════════════
// Token refresh queue
// ════════════════════════════════════════

let isRefreshing = false;
let pendingRequests: Array<(success: boolean) => void> = [];

function resolvePendingRequests(success: boolean) {
  pendingRequests.forEach((callback) => callback(success));
  pendingRequests = [];
}

/**
 * Refresh the access token by calling the refresh endpoint.
 * The refresh_token is sent automatically via HttpOnly Cookie.
 */
export async function refreshAccessToken(): Promise<void> {
  await axios.post('/api/v1/auth/refresh', {}, {
    withCredentials: true,
    headers: buildCommonHeaders(),
  });
  // New tokens are set as HttpOnly cookies by the server — nothing to store locally.
}

// ════════════════════════════════════════
// Common header injection (shared by both Axios and fetch-based SSE)
// ════════════════════════════════════════

/**
 * Build common headers for any outgoing request (CSRF token + request ID).
 * Used by both the Axios client and the SSE fetch client.
 *
 * **Request-id lifecycle (frontend.md §4.6 hard rule).** Pass the id from
 * the previous attempt via ``existingRequestId`` to reuse it — SSE clients
 * must do this on heartbeat reconnect; axios retries do it implicitly via
 * the request interceptor preserving ``config.headers['X-Request-Id']``.
 * Omitting the argument mints a fresh id via ``ensureRequestId()``.
 */
export function buildCommonHeaders(
  existingRequestId?: string | null,
): Record<string, string> {
  const headers: Record<string, string> = {};
  const csrfToken = getCookie('XSRF-TOKEN');
  if (csrfToken) {
    headers['X-XSRF-TOKEN'] = csrfToken;
  }
  headers['X-Request-Id'] = ensureRequestId(existingRequestId);
  return headers;
}

// ════════════════════════════════════════
// Request interceptor
// ════════════════════════════════════════

httpClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const csrfToken = getCookie('XSRF-TOKEN');
    if (csrfToken && config.headers) {
      config.headers['X-XSRF-TOKEN'] = csrfToken;
    }
    if (config.headers) {
      // X-Request-Id reuse invariant (frontend.md §4.6): a 401→refresh→retry
      // cycle flows through this interceptor twice with the SAME config
      // object, and ensureRequestId() keeps the header value verbatim if
      // already set. Never mint a new id on retry — doing so would break
      // log correlation between the original attempt and its retry.
      const current = config.headers['X-Request-Id'];
      config.headers['X-Request-Id'] = ensureRequestId(
        typeof current === 'string' ? current : null,
      );
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// ════════════════════════════════════════
// Response interceptor
// ════════════════════════════════════════

// Success is defined by HTTP status (2xx), not by `code === 200` inside the
// envelope. Per backend.md §6.0 the two should agree, but gating on HTTP
// status lets the gateway's own 5xx (e.g. GATEWAY_INTROSPECT_UNAVAILABLE at
// 503) flow through the normal error path consistently -- axios only fires
// the error branch on non-2xx, so the success branch here is already
// narrowed to "transport-layer 2xx".
httpClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorResponse>) => {
    const originalRequest = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined;

    // 401 auth-refresh fast path: run it BEFORE materializing an ApiError so
    // the caller never sees a transient 401 when the refresh succeeds.
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingRequests.push((success) => {
            if (!success) {
              reject(
                new ApiError({
                  httpStatus: 401,
                  message: 'Authentication required',
                  details: { errorCode: 'GATEWAY_AUTH_REQUIRED', category: 'AUTH' },
                }),
              );
              return;
            }
            resolve(httpClient(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      return refreshAccessToken()
        .then(() => {
          resolvePendingRequests(true);
          return httpClient(originalRequest);
        })
        .catch((refreshError) => {
          resolvePendingRequests(false);
          redirectToLogin();
          return Promise.reject(refreshError);
        })
        .finally(() => {
          isRefreshing = false;
        });
    }

    // Non-recoverable: materialize a structured ApiError. Callers can then
    // dispatch on errorCode (precise) or category (bucket), per §6.3.2.
    if (error.response) {
      return Promise.reject(
        apiErrorFromEnvelope(
          error.response.status,
          error.response.data,
          error.message || 'Request failed',
        ),
      );
    }

    // Transport-layer failure (no HTTP response): DNS, network, timeout.
    // We deliberately leave `details` undefined -- inventing a synthetic
    // errorCode would pollute the §6.3.2 union which is supposed to mirror
    // the backend contract exactly. Consumers should fall back to
    // `httpStatus === 0` to recognise this class of failure.
    return Promise.reject(
      new ApiError({
        httpStatus: 0,
        message: error.message || 'Network error',
      }),
    );
  },
);

// ════════════════════════════════════════
// Typed request helpers
// ════════════════════════════════════════

/**
 * Extract `data` from a success envelope, throwing if absent.
 *
 * Non-2xx responses never reach this helper -- the error interceptor above
 * converts them to ApiError before the caller's `.then(...)` runs. So the
 * only way `response.data` is undefined here is a misbehaving upstream that
 * returned 2xx with an empty body (contract violation of backend.md §6.1).
 * We surface that as ApiError WITHOUT synthesising a backend errorCode --
 * the consumer can recognise "contract-violating 2xx" via httpStatus=200 +
 * absent `details`, the same way it recognises transport failures via
 * httpStatus=0 + absent `details`.
 */
function requireData<T>(response: ApiSuccessResponse<T>, fallbackMessage: string): T {
  if (response.data === undefined) {
    throw new ApiError({
      httpStatus: 200,
      message: response.message || fallbackMessage,
      requestId: response.requestId,
    });
  }
  return response.data;
}

/**
 * Typed GET request that auto-unwraps `ApiSuccessResponse<T>.data`.
 * Non-2xx responses reject with {@link ApiError}.
 */
export async function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.get<ApiSuccessResponse<T>>(url, config);
  return requireData(response.data, 'Response payload is empty');
}

export async function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.post<ApiSuccessResponse<T>>(url, data, config);
  return requireData(response.data, 'Response payload is empty');
}

export async function put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.put<ApiSuccessResponse<T>>(url, data, config);
  return requireData(response.data, 'Response payload is empty');
}

export async function patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.patch<ApiSuccessResponse<T>>(url, data, config);
  return requireData(response.data, 'Response payload is empty');
}

export async function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.delete<ApiSuccessResponse<T>>(url, config);
  return requireData(response.data, 'Response payload is empty');
}

/**
 * POST that expects no data in the response (e.g. 200 with empty data).
 * Does not require a `data` field, so it's safe for `logout` / `refresh`
 * style endpoints whose contract is "200 with empty envelope".
 */
export async function postVoid(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<void> {
  await httpClient.post<ApiSuccessResponse<void>>(url, data, config);
}

export async function putVoid(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<void> {
  await httpClient.put<ApiSuccessResponse<void>>(url, data, config);
}

/**
 * Raw Axios instance for cases that need full control (e.g. custom response handling).
 */
export { httpClient };
export { ApiError } from './apiError';
