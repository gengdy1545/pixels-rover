/**
 * conversation feature 的只读 query hooks。
 *
 * `useThreadsQuery` / `useConversationQuery` 两条是页面 / 侧栏的主要消
 * 费面；不做默认 override，沿用 QueryClient 的 30s staleTime——列表与详
 * 情都是"服务端可能被其它 tab 改"的数据，过 30s 让切回焦点的下次点击
 * 自然刷，避免一直旧。
 *
 * `useConversationQuery(null)` 合法：用 `enabled` 把无 id 的情况挡在
 * 外面；组件可以把 URL 里拿到的 `currentThreadId` 直接塞进来，无需在
 * 调用点自己写 if/else。
 */

import { useQuery } from '@tanstack/react-query';
import { conversationApi } from '../services/conversationApi';
import { conversationKeys } from '../model/queryKeys';

export function useThreadsQuery() {
  return useQuery({
    queryKey: conversationKeys.threads(),
    queryFn: () => conversationApi.listConversations(),
  });
}

export function useConversationQuery(threadId: string | null) {
  return useQuery({
    queryKey: conversationKeys.detail(threadId ?? ''),
    queryFn: () => conversationApi.getConversation(threadId as string),
    enabled: !!threadId,
  });
}
