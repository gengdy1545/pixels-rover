/**
 * Vitest global setup —— 扩 jest-dom matchers + 通用 DOM polyfill。
 *
 * Stage 3 §10 PR-2 从 `src/__tests__/setup.ts` 迁到这里：
 *   - 原 `__tests__/` 下只剩 `pages/Login.test.tsx` 和 `stores/authStore.test.ts`
 *     两个测试文件；这两份测试已经 colocated 到 `features/auth/**`；
 *   - 保留一个 `__tests__/` 顶层目录只是为了容纳 setup.ts，会让 colocated
 *     测试原则出现例外；所以 setup 文件直接放到 `src/test-setup.ts`，根下
 *     一等公民，同时 `__tests__/` 目录被彻底清空/删除。
 *
 * 本文件被 `vite.config.ts` 的 `test.setupFiles` 指定加载；globally 只跑一次
 * （每个测试 worker 内）。放在这里的内容应满足\"所有测试都需要\"，不要把
 * 单测用的桩/mock塞进来（后者应在测试文件自己 vi.mock）。
 */

import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// antd 依赖 matchMedia；jsdom 默认没实现，这里打个最小 polyfill 让 render
// 不炸。返回的对象始终 matches=false——我们不在单测里做 responsive breakpoint
// 断言，触达该条件的组件行为归 E2E。
//
// Guard on `typeof window` 是为了 `@vitest-environment node` pragma 生效的
// 那些纯逻辑测试——vitest 会把 setupFiles 载进每个 worker 的环境里，不论
// 该测试声明的是 jsdom 还是 node；没有这层 guard，node-env 测试在加载
// setup 时就会 ReferenceError，还没开始跑就挂。
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

afterEach(() => {
  cleanup();
});
