/**
 * semantic feature 的 TanStack query key（C1 决策）。
 *
 * semantic metrics / dimensions 由 assistant-service 提供，但 URL
 * 命名空间独立（`/api/v1/semantic/*`，区别于 `/api/v1/analysis/*`）——
 * 所以单独拿一个 feature namespace，不让它与分析生命周期的 key
 * 混进同一棵前缀树。
 *
 * 目前 UI 只消费 `metrics()`；`dimensions()` 保留工厂方法但不产 hook，
 * 等具体消费点出现时一起加，以免先把 UI 不用的缓存预热起来。
 */

import {
  createFeatureKeyFactory,
  type QueryKey,
} from '../../../shared/types/query-keys';

const keys = createFeatureKeyFactory('semantic');

export const semanticKeys = {
  all: keys.all(),
  metrics: (): QueryKey => keys.segment('metrics'),
  dimensions: (): QueryKey => keys.segment('dimensions'),
} as const;
