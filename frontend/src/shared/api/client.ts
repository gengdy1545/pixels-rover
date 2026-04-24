import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { AxiosRequestConfig } from 'axios';
import type { ApiErrorResponse, ApiSuccessResponse } from '../types/common';
import { ensureRequestId } from '../storage/requestId';
import { ensureXsrfCookie } from '../storage/cookie';
import { redirectToLogin } from '../storage/navigation';
import { ApiError, apiErrorFromEnvelope } from './apiError';

// ════════════════════════════════════════
// Axios instance
// ════════════════════════════════════════

// baseURL is resolved from the Vite-time env var ``VITE_API_BASE``.
// Leaving it unset preserves the historical same-origin behavior (the
// browser sends requests to whatever host served the bundle, which is
// APISIX on the production gateway). Setting it — typically during
// local dev against a remote gateway, or for a future non-browser
// client — routes every axios + SSE call through the supplied origin.
// See frontend/.env.example and docs/development/frontend.md.
const API_BASE_URL = (import.meta.env.VITE_API_BASE ?? '').trim();

const httpClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true, // Always send cookies with requests
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Resolve a relative API path to an absolute URL using the same
 * ``VITE_API_BASE`` override honoured by the axios instance. SSE opens
 * go through ``fetch`` rather than axios, so they need to resolve the
 * base URL themselves — exposing this helper keeps the base-URL logic
 * in exactly one file.
 */
export function resolveApiUrl(path: string): string {
  if (!API_BASE_URL) {
    return path;
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const base = API_BASE_URL.replace(/\/+$/, '');
  const tail = path.startsWith('/') ? path : `/${path}`;
  return `${base}${tail}`;
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
  headers['X-XSRF-TOKEN'] = ensureXsrfCookie();
  headers['X-Request-Id'] = ensureRequestId(existingRequestId);
  return headers;
}

// ════════════════════════════════════════
// Request interceptor
// ════════════════════════════════════════

httpClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    if (config.headers) {
      config.headers['X-XSRF-TOKEN'] = ensureXsrfCookie();
    }
    if (config.headers) {
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
// status lets gateway/Oathkeeper failures flow through the normal error path
// consistently -- axios only fires
// the error branch on non-2xx, so the success branch here is already
// narrowed to "transport-layer 2xx".
httpClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorResponse>) => {
    if (error.response?.status === 401) {
      redirectToLogin();
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
