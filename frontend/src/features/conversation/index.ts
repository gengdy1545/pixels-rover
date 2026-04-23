/**
 * `features/conversation` barrel——frontend.md §2 纪律 3 指定的唯一跨
 * feature 入口。
 *
 * 对外暴露：
 *   - 查询 / 变更 hooks（`useThreadsQuery` / `useConversationQuery` /
 *     `useConversationDetailsQueries` / `useCreate*` / `useUpdate*`）——
 *     业务侧消费 conversation 数据的标准面；query key + fetch 策略被锁在
 *     feature 内部，外部只面对 hooks；
 *   - `conversationKeys` 工厂——跨 feature `invalidateQueries` 用的合法
 *     key 句柄（auth 登出、Reports 刷新等需要精确失效时使用）；
 *   - `ConversationList` 组件——侧栏对话列表；Sidebar shell 通过 barrel
 *     消费。
 *
 * 不暴露（硬规则）：
 *   - `conversationApi`——feature 私有 API 客户端。任何需要 "batch 拉多条
 *     detail" 的页面都应消费 `useConversationDetailsQueries(threadIds)`
 *     而非重新组装 `Promise.all(ids.map(api.get))`。Stage 3 §10 PR-3 曾短
 *     期把 `conversationApi` 透出来作为 Reports 的 escape hatch，§10 条 2
 *     完成后此 escape hatch 已撤回——barrel 回到 "只暴露 hooks + keys +
 *     组件" 的干净形态。
 *   - `hooks/` / `model/` / `services/` / `components/` 子路径——任何
 *     `@/features/conversation/<sub>/<file>` 的穿透 import 会被 lint-0 拦下
 *     （frontend.md §3 `no-restricted-imports` 的 "group" 规则）。
 *
 * 历史：原 `stores/conversationStore.ts` 已删除（Stage 2 §12）；
 * `currentThreadId` 由 URL `searchParams` 派生，无独立 store。
 */

export {
  useThreadsQuery,
  useConversationQuery,
  useConversationDetailsQueries,
} from './hooks/useConversationQueries';
export {
  useCreateConversationMutation,
  useUpdateConversationMutation,
} from './hooks/useConversationMutations';
export { conversationKeys } from './model/queryKeys';
export { classifyThreadError } from './model/threadErrors';
export type { ThreadErrorDecision, ThreadErrorKind } from './model/threadErrors';

export { default as ConversationList } from './components/ConversationList';
