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

import { useQueries, useQuery } from '@tanstack/react-query';
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

/**
 * Batch-fetch many thread details at once — the Reports page's core read
 * pattern (per-thread SQL / rows aggregates across the entire user's
 * thread list).
 *
 * Why a dedicated hook instead of a "list the ids, call
 * `useConversationQuery` in a loop" escape hatch:
 *
 *   - Sharing query keys with `useConversationQuery` means the single-thread
 *     cache in Home and the N-thread cache in Reports are the *same*
 *     entries. Navigating Reports → Home → Reports hits cache on every
 *     revisit instead of re-fetching every thread each time.
 *   - Call sites outside this feature (`features/report/...`) never touch
 *     `conversationApi` directly; the barrel can keep `services/` private
 *     per frontend.md §2 "barrel-only cross-feature entry" rule.
 *   - Each sub-query has independent loading / error / retry state, so one
 *     broken thread detail does not collapse the whole report into a banner.
 *     The consumer maps `queries[i].data?.history ?? []` to treat missing
 *     details as "no rows from that thread" rather than a page-wide failure.
 */
export function useConversationDetailsQueries(threadIds: string[]) {
  return useQueries({
    queries: threadIds.map((threadId) => ({
      queryKey: conversationKeys.detail(threadId),
      queryFn: () => conversationApi.getConversation(threadId),
    })),
  });
}
