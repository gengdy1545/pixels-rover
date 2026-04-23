/// <reference types="vitest/config" />
// `defineConfig` must come from `vitest/config` (not `vite`) once vitest 4
// moved the `test` block out of vite's own UserConfig -- otherwise tsc -b
// fails with "test does not exist in type UserConfigExport", blocking the
// production `npm run build` path. Keeping `vite`'s own plugin imports.
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:80',
        changeOrigin: true,
        cookieDomainRewrite: '',
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
});
