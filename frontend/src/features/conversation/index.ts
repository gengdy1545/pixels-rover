/**
 * `features/conversation` barrel（纪律 3 唯一入口）。
 *
 * 不再从这里 re-export 一个 zustand store——Stage 2 把旧
 * `stores/conversationStore.ts` 的服务端快照部分全迁到 TanStack Query，
 * "currentThreadId" 的选中态直接从 URL searchParams 派生（见
 * `pages/Home/index.tsx` 里 `searchParams.get('threadId')`），不再需要
 * 独立 store；旧文件已删除（见 PR 说明）。
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
