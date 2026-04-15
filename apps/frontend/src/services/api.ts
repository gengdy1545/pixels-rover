import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse } from '../types/api';
import { createRequestId } from './requestId';
import { getCookie } from './cookie';

const api = axios.create({
  baseURL: '',
  timeout: 30000,
  withCredentials: true, // Always send cookies with requests
  headers: {
    'Content-Type': 'application/json',
  },
});

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
    headers: {
      'Content-Type': 'application/json',
      'X-Request-Id': createRequestId(),
    },
  });
  // New tokens are set as HttpOnly cookies by the server — nothing to store locally.
}

// Request interceptor: attach CSRF token and request id.
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Read XSRF-TOKEN cookie and send it as X-XSRF-TOKEN header (CSRF double-submit)
    const csrfToken = getCookie('XSRF-TOKEN');
    if (csrfToken && config.headers) {
      config.headers['X-XSRF-TOKEN'] = csrfToken;
    }
    if (config.headers && !config.headers['X-Request-Id']) {
      config.headers['X-Request-Id'] = createRequestId();
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: handle unified {code,message,data,requestId,errorCode} payloads.
api.interceptors.response.use(
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
            resolve(api(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      return refreshAccessToken()
        .then(() => {
          resolvePendingRequests(true);
          return api(originalRequest);
        })
        .catch((refreshError) => {
          resolvePendingRequests(false);
          window.location.href = '/login';
          return Promise.reject(refreshError);
        })
        .finally(() => {
          isRefreshing = false;
        });
    }

    const message = error.response?.data?.message || error.message || 'Network error';
    return Promise.reject(new Error(message));
  }
);

export default api;
