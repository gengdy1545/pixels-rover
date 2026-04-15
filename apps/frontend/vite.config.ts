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
      // Auth API → auth-service (Java/Spring Boot)
      '/api/v1/auth': {
        target: 'http://localhost:8081',
        changeOrigin: true,
        // Ensure Set-Cookie headers from the backend are forwarded to the browser.
        // cookieDomainRewrite rewrites the cookie domain to '' (empty) so that
        // cookies set by localhost:8081 are accepted by the browser on localhost:3000.
        cookieDomainRewrite: '',
      },
      // Chat History API → auth-service (short-term; will migrate to analysis-service)
      '/api/v1/chat': {
        target: 'http://localhost:8081',
        changeOrigin: true,
        cookieDomainRewrite: '',
      },
      // Text-to-SQL API → text2sql service (must be before /api/v1/query)
      '/api/v1/query/text-to-sql': {
        target: 'http://localhost',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api\/v1\/query\/text-to-sql/, '/text2sql'),
      },
      // Query API → Pixels Server (direct proxy)
      '/api/v1/query': {
        target: 'http://localhost:18890',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api\/v1\/query/, '/api/query'),
      },
      // Metadata API → Pixels Server (direct proxy)
      '/api/v1/metadata': {
        target: 'http://localhost:18890',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api\/v1\/metadata/, '/api/metadata'),
      },
      // All other API → analysis-service (Python/FastAPI)
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
