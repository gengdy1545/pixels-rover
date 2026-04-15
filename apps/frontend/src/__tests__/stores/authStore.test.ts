/**
 * Tests for the authStore (zustand) — login state management.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useAuthStore } from '../../stores/authStore';

// Mock the cookie module
vi.mock('../../services/cookie', () => ({
  getCookie: vi.fn(() => null),
  isLoggedInCookie: vi.fn(() => false),
}));

// Mock the authApi module (new unified API layer)
vi.mock('../../api', () => ({
  authApi: {
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

import { authApi } from '../../api';

describe('useAuthStore', () => {
  beforeEach(() => {
    // Reset store state before each test
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
    const mockUser = { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' };
    useAuthStore.getState().setUser(mockUser);

    const state = useAuthStore.getState();
    expect(state.user).toEqual(mockUser);
    expect(state.isAuthenticated).toBe(true);
    expect(state.isLoading).toBe(false);
  });

  it('checkAuth should set user when /me succeeds', async () => {
    const mockUser = { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' };
    // New API layer auto-unwraps ApiResponse — me() resolves directly to UserInfo
    vi.mocked(authApi.me).mockResolvedValue(mockUser);

    await useAuthStore.getState().checkAuth();

    const state = useAuthStore.getState();
    expect(state.user).toEqual(mockUser);
    expect(state.isAuthenticated).toBe(true);
    expect(state.isLoading).toBe(false);
  });

  it('checkAuth should clear user when /me fails', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new Error('Unauthorized'));

    // Start with a user set
    useAuthStore.setState({
      user: { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
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
      user: { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
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
      user: { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
      isAuthenticated: true,
    });

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });
});
