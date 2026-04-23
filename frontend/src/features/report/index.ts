/**
 * `features/report` barrel——frontend.md §2 纪律 3 指定的唯一跨 feature 入口。
 *
 * Reports 目前只在 Home 的 "Reports" 菜单项下挂一个独立视图，消费者只有
 * `pages/Home`；用 `React.lazy` 在 barrel 内部完成 code-split，既保持
 * 按需加载，又不暴露 `features/report/components/Reports` 这种穿透路径
 * （lint-0 精神）。
 *
 * 本 feature 暂时没有独立 model / services：Reports 目前以 on-demand
 * fetch 的方式读 conversation 历史，数据流水依赖 shared/api 的 conversationApi；
 * 后续如果迁 TanStack Query（通过 useQueries 聚合多 thread detail），
 * 再在这里补 hooks / model。
 */

import React from 'react';

export const Reports = React.lazy(() => import('./components/Reports'));
