/**
 * semantic feature 的 query hooks。
 *
 * `useSemanticMetricsQuery` 被 `pages/Analysis` 消费——用户在提问框里
 * 看到的可用指标下拉，需要这张表。staleTime 显式拉长到 5 分钟：语义
 * 模型列表通常一场分析会话（甚至跨多场）都不会动；按 QueryClient 默
 * 认的 30s 会引入"同一面板反复抓同一份 metrics"的浪费。挑 5 分钟等于
 * 承担"刚发布新 metric 时用户最多等 5 分钟看到"，在当前迭代节奏下可
 * 接受；需要更激进的"实时可见"时由调用点显式覆盖或上 SSE 推。
 */

import { useQuery } from '@tanstack/react-query';
import { getSemanticMetrics } from '../../../shared/api';
import { semanticKeys } from '../model/queryKeys';

const FIVE_MINUTES_MS = 5 * 60 * 1000;

export function useSemanticMetricsQuery() {
  return useQuery({
    queryKey: semanticKeys.metrics(),
    queryFn: () => getSemanticMetrics(),
    staleTime: FIVE_MINUTES_MS,
  });
}
