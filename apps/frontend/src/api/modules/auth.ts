import { get, post, postVoid } from '../client';
import type {
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  AccessTokenResponse,
  CaptchaResponse,
  UserInfo,
} from '../../types/user';

export const authApi = {
  login: (data: LoginRequest) =>
    post<TokenResponse>('/api/v1/auth/login', data),

  register: (data: RegisterRequest) =>
    postVoid('/api/v1/auth/register', data),

  getCaptcha: () =>
    get<CaptchaResponse>('/api/v1/auth/captcha'),

  /** Refresh token — the refresh_token is sent automatically via HttpOnly Cookie. */
  refreshToken: () =>
    post<AccessTokenResponse>('/api/v1/auth/refresh', {}),

  getUserInfo: () =>
    get<UserInfo>('/api/v1/auth/user-info'),

  /** Lightweight login-state check. Returns user info if authenticated. */
  me: () =>
    get<UserInfo>('/api/v1/auth/me'),

  /** Logout — clears HttpOnly cookies on the server side. */
  logout: () =>
    postVoid('/api/v1/auth/logout', {}),
};
