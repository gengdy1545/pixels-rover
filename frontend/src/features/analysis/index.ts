/**
 * `features/analysis` barrel——frontend.md §2 纪律 3 指定的唯一跨 feature 入口。
 *
 * 对外暴露：
 *   - `useAnalysisStore`——SSE 驱动的 in-flight 状态 + restoreSession。
 *     Home 需要它来桥接：选中 / 新建对话时，把对应的 `currentThread`
 *     的最新一场分析回灌到 store（`prepareThread` / `restoreSession`），
 *     这样切换会话时 Analysis 视图能立刻看到历史；
 *   - `Analysis`（lazy）——顶层视图组件，Home 把它放进 `<Suspense>` 里
 *     按 chunk 拉，避免首屏带上 CodeMirror / SQL highlighter / ECharts
 *     这堆只有进入分析视图才需要的依赖。
 *
 * 不暴露：
 *   - `analysisApi`（services/）——SSE 流的真正入口，必须经
 *     `useAnalysisStore.startAnalysis` 才能正确接管连接句柄、reducer、
 *     取消语义；任何绕过 store 直接调 `submitAnalysis` 都会让 in-flight
 *     状态机不一致，所以 barrel 故意不放出来；
 *   - `AnalysisInput / TaskCard / PlanTimeline / StepDetail / SummaryCard`
 *     都是页面内部子件，没有 feature 外的合理消费场景，留在 components/
 *     私有；
 *   - `model/store.ts` 内部的 `handleSSEEvent` reducer——是 store 内
 *     部细节，外部消费 store 的公共动作面（startAnalysis / cancelAnalysis
 *     / prepareThread / restoreSession / reset）即可。
 */

import React from 'react';

export { useAnalysisStore } from './model/store';

export const Analysis = React.lazy(() => import('./components/Analysis'));
