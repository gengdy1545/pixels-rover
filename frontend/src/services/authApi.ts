import api from './api';
import type { ApiResponse } from '../types/api';
import type {
  LoginRequest,
  RegisterRequest,
  TokenResponse,
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

  refreshToken: (refreshToken: string) =>
    api.post<ApiResponse<{ accessToken: string }>>('/api/v1/auth/refresh', { refreshToken }),

  getUserInfo: () =>
    api.get<ApiResponse<UserInfo>>('/api/v1/auth/user-info'),
};
