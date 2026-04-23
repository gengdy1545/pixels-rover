/**
 * `features/conversation` barrel——frontend.md §2 纪律 3 指定的唯一跨
 * feature 入口。
 *
 * 对外暴露：
 *   - 查询 / 变更 hooks——业务侧消费 conversation 数据的标准面；
 *   - `conversationKeys` 工厂——跨 feature `invalidateQueries` 用的合法
 *     key 句柄；
 *   - `ConversationList` 组件——侧栏对话列表；Sidebar shell 通过 barrel
 *     消费。
 *   - `conversationApi` —— **escape hatch**。Reports 页（features/report）
 *     需要 N-thread aggregate（`Promise.all(threads.map(getConversation))`），
 *     当前没有现成 hook 覆盖这种 batch 拉取场景。把 conversationApi
 *     从 barrel 透出来作为兼容入口，让 Reports 不必反向穿透
 *     `features/conversation/services/*`。
 *
 *     未来用 `useQueries` 重写 Reports 后，应**移除**此 escape hatch——
 *     hooks 才是 query key 与缓存策略的唯一权威。
 *
 * 历史：原 `stores/conversationStore.ts` 已删除（Stage 2 §12）；
 * `currentThreadId` 由 URL `searchParams` 派生，无独立 store。
 */

export {
  useThreadsQuery,
  useConversationQuery,
} from './hooks/useConversationQueries';
export {
  useCreateConversationMutation,
  useUpdateConversationMutation,
} from './hooks/useConversationMutations';
export { conversationKeys } from './model/queryKeys';

export { default as ConversationList } from './components/ConversationList';

// escape hatch—— 见上方注释，仅用于 Reports 的 N-thread aggregate
export { conversationApi } from './services/conversationApi';
