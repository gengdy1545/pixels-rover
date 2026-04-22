/**
 * Tests for the Login page component.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

// Mock the cookie module (now under shared/storage/)
vi.mock('../../shared/storage/cookie', () => ({
  getCookie: vi.fn(() => null),
  isLoggedInCookie: vi.fn(() => false),
}));

// Mock the authApi module (now under shared/api/)
vi.mock('../../shared/api', () => ({
  authApi: {
    getCaptcha: vi.fn().mockResolvedValue({
      data: {
        code: 200,
        message: 'success',
        data: { captchaKey: 'key-1', captchaImage: 'data:image/png;base64,abc' },
      },
    }),
    login: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

// Mock antd message to avoid act() warnings
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

import Login from '../../pages/Login';

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

    // Check for input placeholders
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
