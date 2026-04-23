/**
 * conversation feature 的 API 客户端封装（Stage 3 §10 PR-3 从 shared/api/modules 迁入）。
 *
 * 归属：list / get / create / update conversation 全部是 conversation 这一
 * feature 的私有 endpoint；由 feature 自己的 hooks（`useThreadsQuery` /
 * `useConversationQuery` / `useCreateConversationMutation` / `useUpdate...`）
 * 消费，不需要 shared/api 这一公共字典。
 *
 * **feature-private**：本模块不从 barrel 对外暴露。历史上 Stage 3 §10 PR-3
 * 曾短期把 `conversationApi` 通过 barrel 透出来，给 Reports 做 N-thread
 * aggregate 的过渡 escape hatch；§10 条 2 完成后，Reports 已改用
 * `useConversationDetailsQueries(threadIds)` 这个 batch-hook 消费，本模块
 * 随之收回成 hooks-only 的私有依赖。
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
