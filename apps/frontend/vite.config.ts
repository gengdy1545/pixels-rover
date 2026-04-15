/// <reference types="vitest" />
import { defineConfig } from 'vite';
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
      '/api/v1/auth': {
        target: 'http://localhost:8081',
        changeOrigin: true,
        // Ensure Set-Cookie headers from the backend are forwarded to the browser.
        // cookieDomainRewrite rewrites the cookie domain to '' (empty) so that
        // cookies set by localhost:8081 are accepted by the browser on localhost:3000.
        cookieDomainRewrite: '',
      },
      '/api': {
        target: 'http://localhost:8090',
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
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
});
