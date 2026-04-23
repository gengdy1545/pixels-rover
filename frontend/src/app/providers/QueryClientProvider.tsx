/**
 * 全局 TanStack Query provider ——决策 C1 的运行时落点。
 *
 * 这是全仓唯一的 `QueryClient` 实例来源；`main.tsx` 把它挂在 `BrowserRouter`
 * 外层，feature 通过 `useQuery` / `useMutation` 间接使用。业务侧**不**应该
 * 再 `new QueryClient()`——多实例 = 多缓存，等于彻底绕过了 TanStack 的统一
 * 失效路径。
 *
 * 默认值的取舍（详见 `.notes/todolist.md §12 C1` 讨论）：
 *
 *   - `queries.retry = false`
 *     axios 客户端（`shared/api/client.ts`）内部已经实现了 401 → refresh →
 *     原请求重放的队列；除此之外其它错误都不应该默认重试——backend.md §6.0
 *     里的每个 errorCode 都是可能承担 UX 分支的，静默重试会让"我点了一下
 *     怎么又来了一个新 errorCode"变成不可复现的断面。真正想重试的查询
 *     （例如 schema 列表轮询）在调用点 `useQuery({ retry: n })` 显式开。
 *
 *   - `queries.refetchOnWindowFocus = false`
 *     跨标签页自动刷新在这种 BI 风格 UI 里噪声远大于收益——stale list 不是
 *     致命 UX，但强制刷新会打断用户手里正写的分析。callers 按需 override。
 *
 *   - `queries.refetchOnReconnect = true`
 *     离线 → 重新联网是明确的"有新数据可能"信号，默认追一下是合理的。
 *
 *   - `queries.staleTime = 30_000` / `queries.gcTime = 5 * 60_000`
 *     大多数后台列表数据 30 秒内 stale-while-revalidate 够用；GC 给 5 分钟
 *     是为了标签切换 / 快速前后跳转时不重拉整页。
 *
 *   - `mutations.retry = false`
 *     mutation 默认不重试；幂等性需要由调用点自证。
 *
 * Devtools 只在 `import.meta.env.DEV` 挂载——production bundle 不应该打进去。
 */

import React from 'react';
import {
  QueryClient,
  QueryClientProvider as TanstackQueryClientProvider,
} from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

const THIRTY_SECONDS_MS = 30_000;
const FIVE_MINUTES_MS = 5 * 60 * 1000;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      staleTime: THIRTY_SECONDS_MS,
      gcTime: FIVE_MINUTES_MS,
    },
    mutations: {
      retry: false,
    },
  },
});

/**
 * App-level provider wrapper.
 *
 * 提供给 `main.tsx` 使用，确保所有渲染在 `<AppQueryClientProvider>` 内部的
 * 组件共享同一个 `QueryClient` 实例。顺便在 dev 环境下挂 devtools 面板。
 */
export const AppQueryClientProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  return (
    <TanstackQueryClientProvider client={queryClient}>
      {children}
      {import.meta.env.DEV && (
        <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-left" />
      )}
    </TanstackQueryClientProvider>
  );
};
