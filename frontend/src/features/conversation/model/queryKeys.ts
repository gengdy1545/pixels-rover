/**
 * conversation feature 的 TanStack query key（C1 决策）。
 *
 * 两类 key：
 *   - `threads()` —— 当前用户的 thread 列表（侧栏 + 新建跳转消费）；
 *   - `detail(threadId)` —— 某个 thread 的完整详情（含 history[]）。
 *
 * Mutation 成功后的失效粒度：
 *   - `createConversation` —— invalidate `threads()`（新元素进列表）；
 *     detail 不用 invalidate，新线程返回的 thread 本身尚无 history；
 *   - `updateConversation` —— invalidate **两者**：列表里的 title /
 *     backendId 可能改了，detail 缓存里的 thread 字段也要跟着刷。
 */

import {
  createFeatureKeyFactory,
  type QueryKey,
} from '../../../shared/types/query-keys';

const keys = createFeatureKeyFactory('conversation');

export const conversationKeys = {
  all: keys.all(),
  threads: (): QueryKey => keys.segment('threads'),
  detail: (threadId: string): QueryKey => keys.segment('detail', threadId),
} as const;
