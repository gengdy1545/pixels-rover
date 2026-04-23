import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

vi.mock('../../../../shared/storage/navigation', () => ({
  redirectToLogin: vi.fn(),
}));

import { redirectToLogin } from '../../../../shared/storage/navigation';
import Login from './index';

describe('Login Page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('redirects to the Ory Kratos login browser flow', () => {
    render(React.createElement(Login));

    expect(redirectToLogin).toHaveBeenCalledWith('/home');
  });
});
