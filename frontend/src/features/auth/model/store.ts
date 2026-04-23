/**
 * auth feature 的客户端身份状态（Stage 3 §10 PR-2 迁位到 features/auth）。
 *
 * 这里装的是**纯客户端视角的登录态快照**——Kratos `/sessions/whoami`
 * 映射出的 `UserInfo`，以及初次 whoami 查询期间的 `isLoading`。真正的
 * 访问控制由 Kratos/Oathkeeper 在网关后侧完成。
 *
 * 为什么不迁到 TanStack Query：
 *   - 登录态来自 Kratos session cookie，前端只能把 whoami 结果当 UI 提示。
 *   - `setUser` / `logout` 的清理路径会顺带清掉任何 UI 残影（avatar /
 *     name 展示），不是纯 GET 语义。
 *   - 上游 401 由 `shared/api/client.ts` 触发 Ory 登录跳转；store 只负责
 *     "认证失败就把 UI 清空"。
 *
 * `checkAuth` 故意 swallow 所有错误只置空状态：/me 失败的正常原因就是未
 * 登录或 token 过期，消费方（路由 guard）只需要一个 true/false 信号；把
 * 具体 `ApiError` 透出去反而让 guard 必须再分派一次。
 */

import { create } from 'zustand';
import type { UserInfo } from '../../../shared/types/user';
import { authApi } from '../services/authApi';

interface AuthState {
  user: UserInfo | null;
  /** UI hint only. Real auth is enforced by Kratos/Oathkeeper. */
  isAuthenticated: boolean;
  /** True while the initial Kratos whoami check is in flight. */
  isLoading: boolean;
  setUser: (user: UserInfo) => void;
  /**
   * Check login state by calling Kratos GET /sessions/whoami.
   * The HttpOnly Kratos session cookie is sent automatically.
   */
  checkAuth: () => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

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
