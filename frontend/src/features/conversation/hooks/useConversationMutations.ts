/**
 * conversation feature 的 mutation hooks。
 *
 * 失效粒度（见 `model/queryKeys.ts` 注释的联动表）：
 *   - create 成功 → invalidate `threads()`；新 thread 没 history，不需要
 *     主动 prefetch `detail()`；调用方如果紧接着 navigate 到 detail，
 *     TanStack 会按正常 enabled=true 路径自然加载。
 *   - update 成功 → invalidate `threads()` **且** `detail(threadId)`：
 *     update 可能改 title / schema / backendId，两个缓存都可能持旧拷贝。
 *
 * Mutation 签名里不用 `ApiError` 泛型——axios 客户端已经把非 2xx 转成
 * `ApiError` 抛出（见 `shared/api/client.ts` response interceptor），
 * TanStack 侧拿到的就是结构化错误；组件消费 `mutation.error` 时可以按
 * `backend.md §6.3.2` 的两级分派。
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { conversationApi } from '../services/conversationApi';
import type {
  ConversationThread,
  CreateConversationRequest,
  UpdateConversationRequest,
} from '../../../shared/types/conversation';
import { conversationKeys } from '../model/queryKeys';

export function useCreateConversationMutation() {
  const queryClient = useQueryClient();
  return useMutation<ConversationThread, Error, CreateConversationRequest>({
    mutationFn: (input) => conversationApi.createConversation(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: conversationKeys.threads() });
    },
  });
}

export function useUpdateConversationMutation() {
  const queryClient = useQueryClient();
  return useMutation<
    ConversationThread,
    Error,
    { threadId: string; input: UpdateConversationRequest }
  >({
    mutationFn: ({ threadId, input }) =>
      conversationApi.updateConversation(threadId, input),
    onSuccess: (thread) => {
      queryClient.invalidateQueries({ queryKey: conversationKeys.threads() });
      queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(thread.threadId),
      });
    },
  });
}
