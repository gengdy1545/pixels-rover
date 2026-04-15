import { create } from 'zustand';
import type { UserInfo } from '../types/user';
import { authApi } from '../api';
import { isLoggedInCookie } from '../services/cookie';

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
  isLoading: isLoggedInCookie(), // only need to load if cookie hints at login

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
      // Best-effort: even if the server call fails, clear local state
    }
    set({ user: null, isAuthenticated: false, isLoading: false });
  },
}));
