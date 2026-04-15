/**
 * Tests for AppRouter — route guards (PrivateRoute / PublicRoute).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';
import { useAuthStore } from '../../stores/authStore';

// Mock the cookie module
vi.mock('../../services/cookie', () => ({
  getCookie: vi.fn(() => null),
  isLoggedInCookie: vi.fn(() => false),
}));

// Mock the authApi module
vi.mock('../../services/authApi', () => ({
  authApi: {
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

// Mock lazy-loaded pages with simple components
vi.mock('../../pages/Login', () => ({
  default: () => React.createElement('div', { 'data-testid': 'login-page' }, 'Login Page'),
}));
vi.mock('../../pages/Register', () => ({
  default: () => React.createElement('div', { 'data-testid': 'register-page' }, 'Register Page'),
}));
vi.mock('../../pages/Home', () => ({
  default: () => React.createElement('div', { 'data-testid': 'home-page' }, 'Home Page'),
}));

import AppRouter from '../../router/index';

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
