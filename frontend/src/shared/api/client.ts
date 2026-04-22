import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { AxiosRequestConfig } from 'axios';
import type { ApiResponse } from '../types/api';
import { createRequestId } from '../storage/requestId';
import { getCookie } from '../storage/cookie';
import { redirectToLogin } from '../storage/navigation';

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
 */
export function buildCommonHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const csrfToken = getCookie('XSRF-TOKEN');
  if (csrfToken) {
    headers['X-XSRF-TOKEN'] = csrfToken;
  }
  headers['X-Request-Id'] = createRequestId();
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
    if (config.headers && !config.headers['X-Request-Id']) {
      config.headers['X-Request-Id'] = createRequestId();
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// ════════════════════════════════════════
// Response interceptor
// ════════════════════════════════════════

httpClient.interceptors.response.use(
  (response) => {
    const data = response.data;
    if (data && typeof data === 'object' && 'code' in data) {
      if ((data as ApiResponse).code !== 200) {
        return Promise.reject(new Error((data as ApiResponse).message || 'Request failed'));
      }
    }
    return response;
  },
  (error: AxiosError<ApiResponse>) => {
    const originalRequest = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingRequests.push((success) => {
            if (!success) {
              reject(new Error('Authentication required'));
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

    const message = error.response?.data?.message || error.message || 'Network error';
    return Promise.reject(new Error(message));
  },
);

// ════════════════════════════════════════
// Typed request helpers
// ════════════════════════════════════════

/**
 * Extract `data` from an `ApiResponse<T>` payload, throwing if absent.
 */
function requireData<T>(response: ApiResponse<T>, fallbackMessage: string): T {
  if (response.data === undefined) {
    throw new Error(response.message || fallbackMessage);
  }
  return response.data;
}

/**
 * Typed GET request that auto-unwraps `ApiResponse<T>.data`.
 */
export async function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.get<ApiResponse<T>>(url, config);
  return requireData(response.data, 'Response payload is empty');
}

/**
 * Typed POST request that auto-unwraps `ApiResponse<T>.data`.
 */
export async function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.post<ApiResponse<T>>(url, data, config);
  return requireData(response.data, 'Response payload is empty');
}

/**
 * Typed PUT request that auto-unwraps `ApiResponse<T>.data`.
 */
export async function put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.put<ApiResponse<T>>(url, data, config);
  return requireData(response.data, 'Response payload is empty');
}

/**
 * Typed PATCH request that auto-unwraps `ApiResponse<T>.data`.
 */
export async function patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.patch<ApiResponse<T>>(url, data, config);
  return requireData(response.data, 'Response payload is empty');
}

/**
 * Typed DELETE request that auto-unwraps `ApiResponse<T>.data`.
 */
export async function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await httpClient.delete<ApiResponse<T>>(url, config);
  return requireData(response.data, 'Response payload is empty');
}

/**
 * POST that expects no data in the response (e.g. 200 with empty data).
 * Does not throw on missing `data` field.
 */
export async function postVoid(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<void> {
  await httpClient.post<ApiResponse<void>>(url, data, config);
}

/**
 * PUT that expects no data in the response.
 */
export async function putVoid(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<void> {
  await httpClient.put<ApiResponse<void>>(url, data, config);
}

/**
 * Raw Axios instance for cases that need full control (e.g. custom response handling).
 */
export { httpClient };
