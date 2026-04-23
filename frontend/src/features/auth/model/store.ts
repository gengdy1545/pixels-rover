/**
 * auth feature 的客户端身份状态（Stage 3 §10 PR-2 迁位到 features/auth）。
 *
 * 这里装的是**纯客户端视角的登录态快照**——`/api/v1/auth/me` 返回的
 * `UserInfo`、基于 `logged_in` cookie 的乐观 `isAuthenticated` 提示，以及
 * 初次 `/me` 查询期间的 `isLoading`。不装**服务端验收后的结果**（那完全
 * 由 HttpOnly `access_token` cookie + gateway-auth 决定）——backend.md §2
 * / gateway.md §4 已经规定前端对登录态的判断是**提示性**的，真正的拦截
 * 由网关完成。
 *
 * 为什么不迁到 TanStack Query：
 *   - `isAuthenticated` 乐观态源自 cookie，而不是 `/me` 的 loading cycle；
 *     把它塞进 `useQuery` 会让 cookie 读 / query 状态两条路径互相踩脚。
 *   - `setUser` / `logout` 的清理路径会顺带清掉任何 UI 残影（avatar /
 *     name 展示），不是纯 GET 语义。
 *   - 上游 401 → refresh 重放队列由 `shared/api/client.ts` 承担；store 只
 *     负责 "认证失败就把 UI 清空"。
 *
 * `checkAuth` 故意 swallow 所有错误只置空状态：/me 失败的正常原因就是未
 * 登录或 token 过期，消费方（路由 guard）只需要一个 true/false 信号；把
 * 具体 `ApiError` 透出去反而让 guard 必须再分派一次。
 */

import { create } from 'zustand';
import type { UserInfo } from '../../../shared/types/user';
import { isLoggedInCookie } from '../../../shared/storage/cookie';
import { authApi } from '../services/authApi';

interface AuthState {
  user: UserInfo | null;
  /** Optimistic UI hint based on the logged_in cookie. Real auth is server-side. */
  isAuthenticated: boolean;
  /** True while the initial /me check is in flight. */
  isLoading: boolean;
  setUser: (user: UserInfo) => void;
  /**
   * Check login state by calling GET /api/v1/auth/me.
   * The HttpOnly access_token cookie is sent automatically.
   */
  checkAuth: () => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: isLoggedInCookie(),
  isLoading: isLoggedInCookie(),

  setUser: (user: UserInfo) => {
    set({ user, isAuthenticated: true, isLoading: false });
  },

  checkAuth: async () => {
    try {
      const user = await authApi.me();
      if (user) {
        set({ user, isAuthenticated: true, isLoading: false });
      } else {
        set({ user: null, isAuthenticated: false, isLoading: false });
      }
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  logout: async () => {
    try {
      await authApi.logout();
    } catch {
      // Best-effort: server call may fail (network, etc.); local state still gets cleared.
    }
    set({ user: null, isAuthenticated: false, isLoading: false });
  },
}));
