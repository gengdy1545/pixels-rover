import api from './api';
import type { ApiResponse } from '../types/api';
import type {
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  AccessTokenResponse,
  CaptchaResponse,
  UserInfo,
} from '../types/user';

export const authApi = {
  login: (data: LoginRequest) =>
    api.post<ApiResponse<TokenResponse>>('/api/v1/auth/login', data),

  register: (data: RegisterRequest) =>
    api.post<ApiResponse<void>>('/api/v1/auth/register', data),

  getCaptcha: () =>
    api.get<ApiResponse<CaptchaResponse>>('/api/v1/auth/captcha'),

  /** Refresh token — the refresh_token is sent automatically via HttpOnly Cookie. */
  refreshToken: () =>
    api.post<ApiResponse<AccessTokenResponse>>('/api/v1/auth/refresh', {}),

  getUserInfo: () =>
    api.get<ApiResponse<UserInfo>>('/api/v1/auth/user-info'),

  /** Lightweight login-state check. Returns user info if authenticated. */
  me: () =>
    api.get<ApiResponse<UserInfo>>('/api/v1/auth/me'),

  /** Logout — clears HttpOnly cookies on the server side. */
  logout: () =>
    api.post<ApiResponse<void>>('/api/v1/auth/logout', {}),
};
