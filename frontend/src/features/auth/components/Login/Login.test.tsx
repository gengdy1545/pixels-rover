/**
 * Login 页面的 smoke 测试（colocated，Stage 3 §10 PR-2 迁入）。
 *
 * 搬迁影响：
 *   - 历史位置 `src/__tests__/pages/Login.test.tsx` 已随 PR-2 删除；
 *   - 路径从"跨越 __tests__ → pages"变成"同目录 index.tsx"，所有 mock
 *     目标都要相对本文件重新指向；
 *   - `authApi` 已从 `shared/api` 撤 re-export，改成本 feature 的
 *     `../../services/authApi`——mock path 跟组件内部 import 保持一致。
 *
 * 测试意图没变：验证 Login 页首屏 render 出 email / password / captcha 输
 * 入 + Sign In 按钮 + 注册链接。真正的登录流程 / 错误分派走 E2E，不在这
 * 个 colocated suite 的覆盖里。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

vi.mock('../../../../shared/storage/cookie', () => ({
  getCookie: vi.fn(() => null),
  isLoggedInCookie: vi.fn(() => false),
}));

// authApi 已迁到 feature 内部；`get<T>` / `postVoid` 自动 unwrap envelope，
// 所以 `getCaptcha()` resolve 的是 `CaptchaResponse` 本体，不是外层 envelope。
vi.mock('../../services/authApi', () => ({
  authApi: {
    getCaptcha: vi.fn().mockResolvedValue({
      captchaKey: 'key-1',
      captchaImage: 'data:image/png;base64,abc',
    }),
    login: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

// 避免 antd message 产生 act() 警告
vi.mock('antd', async () => {
  const actual = await vi.importActual('antd');
  return {
    ...actual,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      info: vi.fn(),
      warning: vi.fn(),
    },
  };
});

import Login from './index';

describe('Login Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render the login form with email, password, and captcha fields', async () => {
    render(
      React.createElement(MemoryRouter, null,
        React.createElement(Login)
      )
    );

    expect(screen.getByPlaceholderText('username (email)')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('password')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('verification code')).toBeInTheDocument();
  });

  it('should render the Sign In button', () => {
    render(
      React.createElement(MemoryRouter, null,
        React.createElement(Login)
      )
    );

    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('should render the register link', () => {
    render(
      React.createElement(MemoryRouter, null,
        React.createElement(Login)
      )
    );

    expect(screen.getByText(/don't have an account/i)).toBeInTheDocument();
  });
});
