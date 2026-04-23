/**
 * auth feature 的 API 客户端封装（Stage 3 §10 PR-2 从 shared/api/modules 迁入）。
 *
 * 归属判断（frontend.md §2 纪律 3 / §1.1.1）：
 *   - `shared/api/` 只应承担**跨 feature、通用**的 HTTP 能力：axios 实例、
 *     envelope 解包、401 refresh 重放、SSE 流水线。
 *   - 具体业务 endpoint（login / register / me / logout / captcha）是
 *     auth feature 的私有调用面——只被 `model/store.ts` 和
 *     `components/{Login,Register}` 消费。把它挪进 feature 内部后，
 *     跨 feature 代码就不再把 `authApi` 看成"公共字典"。
 *
 * 刻意不从 barrel 对外 re-export：其它 feature 要登录状态请读
 * `useAuthStore`；要触发登录就跳 `/login` 路由；永远不需要直接拿 authApi。
 */

import { get, postVoid } from '../../../shared/api/client';
import type {
  LoginRequest,
  RegisterRequest,
  CaptchaResponse,
  UserInfo,
} from '../../../shared/types/user';

export const authApi = {
  login: (data: LoginRequest) =>
    postVoid('/api/v1/auth/login', data),

  register: (data: RegisterRequest) =>
    postVoid('/api/v1/auth/register', data),

  getCaptcha: () =>
    get<CaptchaResponse>('/api/v1/auth/captcha'),

  /** Refresh token — the refresh_token is sent automatically via HttpOnly Cookie. */
  refreshToken: () =>
    postVoid('/api/v1/auth/refresh', {}),

  getUserInfo: () =>
    get<UserInfo>('/api/v1/auth/user-info'),

  /** Lightweight login-state check. Returns user info if authenticated. */
  me: () =>
    get<UserInfo>('/api/v1/auth/me'),

  /** Logout — clears HttpOnly cookies on the server side. */
  logout: () =>
    postVoid('/api/v1/auth/logout', {}),
};
