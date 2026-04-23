/**
 * AppRouter 的路由 guard 测试（PrivateRoute / PublicRoute）。
 *
 * Stage 3 §10 PR-2 重指 mock 后：
 *   - `useAuthStore` 从 `features/auth` barrel 拿，跟 AppRouter 本身的
 *     import 保持一致；
 *   - cookie / authApi 的 mock path 不再走 `shared/api`（已从 barrel 撤下
 *     authApi）——直接 stub `features/auth/services/authApi`；
 *   - Login / Register 的 lazy 组件在 barrel 里声明，所以直接 mock
 *     `features/auth` barrel 的 Login / Register 引用会破坏 `useAuthStore`
 *     等同路径的导出——改为 mock 更底层的组件文件路径
 *     （`features/auth/components/Login`），让 barrel 的 lazy 动态 import
 *     自然解析到被替换的 stub。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';
import { useAuthStore } from '../../features/auth';

vi.mock('../../shared/storage/cookie', () => ({
  getCookie: vi.fn(() => null),
  isLoggedInCookie: vi.fn(() => false),
}));

vi.mock('../../features/auth/services/authApi', () => ({
  authApi: {
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

// barrel 内部用 `React.lazy(() => import('./components/Login'))` 拼 Login；
// mock 被 lazy 动态 import 的模块文件而非 barrel 本身——后者会把
// `useAuthStore` 等正常导出也吃掉。
vi.mock('../../features/auth/components/Login', () => ({
  default: () => React.createElement('div', { 'data-testid': 'login-page' }, 'Login Page'),
}));
vi.mock('../../features/auth/components/Register', () => ({
  default: () => React.createElement('div', { 'data-testid': 'register-page' }, 'Register Page'),
}));
vi.mock('../../pages/Home', () => ({
  default: () => React.createElement('div', { 'data-testid': 'home-page' }, 'Home Page'),
}));

import AppRouter from './index';

describe('AppRouter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should redirect unauthenticated user from /home to /login', async () => {
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });

    render(
      React.createElement(MemoryRouter, { initialEntries: ['/home'] },
        React.createElement(AppRouter)
      )
    );

    const loginPage = await screen.findByTestId('login-page');
    expect(loginPage).toBeInTheDocument();
  });

  it('should show home page for authenticated user', async () => {
    useAuthStore.setState({
      user: { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
      isAuthenticated: true,
      isLoading: false,
    });

    render(
      React.createElement(MemoryRouter, { initialEntries: ['/home'] },
        React.createElement(AppRouter)
      )
    );

    const homePage = await screen.findByTestId('home-page');
    expect(homePage).toBeInTheDocument();
  });

  it('should redirect authenticated user from /login to /home', async () => {
    useAuthStore.setState({
      user: { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
      isAuthenticated: true,
      isLoading: false,
    });

    render(
      React.createElement(MemoryRouter, { initialEntries: ['/login'] },
        React.createElement(AppRouter)
      )
    );

    const homePage = await screen.findByTestId('home-page');
    expect(homePage).toBeInTheDocument();
  });

  it('should show login page for unauthenticated user at /login', async () => {
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    });

    render(
      React.createElement(MemoryRouter, { initialEntries: ['/login'] },
        React.createElement(AppRouter)
      )
    );

    const loginPage = await screen.findByTestId('login-page');
    expect(loginPage).toBeInTheDocument();
  });

  it('should redirect / to /home', async () => {
    useAuthStore.setState({
      user: { id: 1, name: 'Alice', email: 'alice@example.com', affiliation: 'PixelsDB' },
      isAuthenticated: true,
      isLoading: false,
    });

    render(
      React.createElement(MemoryRouter, { initialEntries: ['/'] },
        React.createElement(AppRouter)
      )
    );

    const homePage = await screen.findByTestId('home-page');
    expect(homePage).toBeInTheDocument();
  });
});
