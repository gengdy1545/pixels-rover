/**
 * conversation feature 的 API 客户端封装（Stage 3 §10 PR-3 从 shared/api/modules 迁入）。
 *
 * 归属：list / get / create / update conversation 全部是 conversation 这一
 * feature 的私有 endpoint；由 feature 自己的 hooks（`useThreadsQuery` /
 * `useConversationQuery` / `useCreateConversationMutation` / `useUpdate...`）
 * 消费，不需要 shared/api 这一公共字典。
 *
 * 对外 escape hatch（见 `../index.ts` barrel 注释）：
 *   `Reports` 页面（features/report）在做 N-thread aggregate 时直接
 *   `await Promise.all(threads.map(getConversation))`——这种 batch 拉取没
 *   有现成的 hook 覆盖（hooks 都是单个 thread 的 single-cache 视图）。
 *   barrel 上把 conversationApi 暴露出去作为兼容入口，保留\"未来用
 *   `useQueries` 重写 Reports 后撤回\"的弹性。
 */

import { get, patch, post } from '../../../shared/api/client';
import type {
  ConversationDetail,
  ConversationThread,
  CreateConversationRequest,
  UpdateConversationRequest,
} from '../../../shared/types/conversation';

export const conversationApi = {
  createConversation: (data: CreateConversationRequest) =>
    post<ConversationThread>('/api/v1/conversations', data),

  listConversations: () =>
    get<ConversationThread[]>('/api/v1/conversations'),

  getConversation: (threadId: string) =>
    get<ConversationDetail>(`/api/v1/conversations/${threadId}`),

  updateConversation: (threadId: string, data: UpdateConversationRequest) =>
    patch<ConversationThread>(`/api/v1/conversations/${threadId}`, data),
};
