/**
 * colocated 测试（Stage 3 §10 PR-2）——authStore 的契约。
 *
 * 历史位置：`src/__tests__/stores/authStore.test.ts`。搬到 feature 内部后：
 *   - mock 路径回落到相对本文件的 `../services/authApi` / `../../../shared/storage/cookie`；
 *   - 不再跨层拉 `../../shared/api` 的 `authApi`——PR-2 已经把 authApi 从
 *     `shared/api/index.ts` 撤下；作为 feature 内部 API 客户端它的唯一消
 *     费者就是本 feature 的 store / UI。
 *   - features/<name>/model/ 在 lint-1 受限制下默认禁 react / antd / router，
 *     本测试本身不触发这些（纯状态机断言）所以保持合规；即便 barrel lint
 *     也对所有 .test 文件豁免（见 `.eslintrc.cjs` overrides）。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAuthStore } from './store';

vi.mock('../../../shared/storage/cookie', () => ({
  getCookie: vi.fn(() => null),
  isLoggedInCookie: vi.fn(() => false),
}));

vi.mock('../services/authApi', () => ({
  authApi: {
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

import { authApi } from '../services/authApi';

describe('useAuthStore', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });
    vi.clearAllMocks();
  });

  it('should have correct initial state', () => {
    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
    expect(state.isLoading).toBe(false);
  });

  it('setUser should update user and isAuthenticated', () => {
    const mockUser = { id: 'user-1', name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' };
    useAuthStore.getState().setUser(mockUser);

    const state = useAuthStore.getState();
    expect(state.user).toEqual(mockUser);
    expect(state.isAuthenticated).toBe(true);
    expect(state.isLoading).toBe(false);
  });

  it('checkAuth should set user when /me succeeds', async () => {
    const mockUser = { id: 'user-1', name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' };
    // Kratos whoami is mapped directly to UserInfo by authApi.me().
    vi.mocked(authApi.me).mockResolvedValue(mockUser);

    await useAuthStore.getState().checkAuth();

    const state = useAuthStore.getState();
    expect(state.user).toEqual(mockUser);
    expect(state.isAuthenticated).toBe(true);
    expect(state.isLoading).toBe(false);
  });

  it('checkAuth should clear user when /me fails', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new Error('Unauthorized'));

    useAuthStore.setState({
      user: { id: 'user-1', name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
      isAuthenticated: true,
    });

    await useAuthStore.getState().checkAuth();

    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
    expect(state.isLoading).toBe(false);
  });

  it('logout should clear state and call authApi.logout', async () => {
    vi.mocked(authApi.logout).mockResolvedValue(undefined as never);

    useAuthStore.setState({
      user: { id: 'user-1', name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
      isAuthenticated: true,
    });

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
    expect(authApi.logout).toHaveBeenCalledOnce();
  });

  it('logout should clear state even if server call fails', async () => {
    vi.mocked(authApi.logout).mockRejectedValue(new Error('Network error'));

    useAuthStore.setState({
      user: { id: 'user-1', name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
      isAuthenticated: true,
    });

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });
});
