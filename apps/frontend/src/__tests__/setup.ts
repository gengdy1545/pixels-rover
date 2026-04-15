/**
 * Vitest global setup — extends matchers with jest-dom and configures MSW.
 */
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Automatically unmount React trees after each test
afterEach(() => {
  cleanup();
});
