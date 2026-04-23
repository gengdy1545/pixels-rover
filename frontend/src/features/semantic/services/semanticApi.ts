/**
 * semantic feature 的 API 客户端封装（Stage 3 §10 PR-4 从 shared/api/modules/analysis 拆出）。
 *
 * 历史：assistant-service 把语义层接口挂在 `/api/v1/semantic/*`，旧版前端
 * 把它和 analysis endpoint 一起塞进 `shared/api/modules/analysis.ts`，
 * 因为消费侧（pages/Analysis）是同一个。Stage 3 §10 把消费拆到两个 feature
 * 后，原 module 就失去了"共宿主"理由——按 endpoint 真实归属拆到
 * `features/semantic/services/`，让 metrics / dimensions 缓存独立。
 *
 * 当前只用到 `getSemanticMetrics`（被 `useSemanticMetricsQuery` 包；唯一
 * 调用点：分析输入框的"可用指标"下拉）。`getSemanticDimensions` 暂无
 * 调用点但保留，原因：契约面已经定义、后续维度选择器要用，删了再加只
 * 是来回搬同一段代码。
 *
 * 不从 barrel 暴露：所有外部消费走 `useSemanticMetricsQuery`，把 query key
 * + staleTime 锁死在 hook 里，避免野调。
 */

import { get } from '../../../shared/api/client';
import type {
  SemanticMetric,
  SemanticDimension,
} from '../../../shared/types/analysis';

/** Get available semantic metrics. */
export function getSemanticMetrics(): Promise<SemanticMetric[]> {
  return get<SemanticMetric[]>('/api/v1/semantic/metrics');
}

/** Get available semantic dimensions. */
export function getSemanticDimensions(): Promise<SemanticDimension[]> {
  return get<SemanticDimension[]>('/api/v1/semantic/dimensions');
}
