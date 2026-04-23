/**
 * `features/report` barrel——frontend.md §2 纪律 3 指定的唯一跨 feature 入口。
 *
 * Reports 目前只在 Home 的 "Reports" 菜单项下挂一个独立视图，消费者只有
 * `pages/Home`；用 `React.lazy` 在 barrel 内部完成 code-split，既保持
 * 按需加载，又不暴露 `features/report/components/Reports` 这种穿透路径
 * （lint-0 精神）。
 *
 * 本 feature 暂时没有独立 model / services：Reports 以 `features/conversation`
 * 暴露的 `useConversationDetailsQueries` / `useThreadsQuery` hooks 读 N-thread
 * aggregate，数据流水完全走 TanStack Query 的共享缓存（与 Home 页的单
 * thread detail 缓存同源）。一旦后续需要自有类型 / 服务（比如独立的报表
 * 指标接口），再在这里补 `model/` / `services/`。
 */

import React from 'react';

export const Reports = React.lazy(() => import('./components/Reports'));
