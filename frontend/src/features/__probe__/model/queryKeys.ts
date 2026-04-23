/**
 * C1 query-key 分层的"活例"——给后续真实 feature（auth / analysis /
 * conversation / schema / backends / semantic）复制粘贴的骨架。
 *
 * 本文件特意放在 `features/__probe__/model/` 下，同时命中两条纪律：
 *
 *   - lint-1（纪律 1）：`features/*\/model/**` 禁 react / react-router-dom /
 *     antd。本文件只 import `shared/types/query-keys`，在 model 层没有任何
 *     渲染层依赖——如果有人误把 `useQuery` 搬进来，lint-1 会立刻报错。
 *     换言之：key 工厂是 model 层资产；`useXxxQuery` hook 是 hooks 层资产。
 *
 *   - C1：第 0 段 namespace 是 `FeatureNamespace` 里注册过的字面量，不允
 *     许出现野 key。
 *
 * 真正的 feature 应该参照这份骨架，在自己的
 * `features/<name>/model/queryKeys.ts` 里：
 *
 *   export const <name>Keys = {
 *     all: keys.all(),
 *     detail: (id: string) => keys.segment('detail', id),
 *     list: (filter: SomeFilter) => keys.segment('list', filter),
 *   } as const;
 *
 * 然后在 `features/<name>/index.ts` barrel 里 `export { <name>Keys }`，
 * 让跨 feature 失效（如 auth 登出 → 清空 analysis 缓存）能走 lint-0
 * 允许的唯一入口。
 */

import {
  createFeatureKeyFactory,
  type QueryKey,
} from '../../../shared/types/query-keys';

const keys = createFeatureKeyFactory('__probe__');

export const probeKeys = {
  all: keys.all(),
  hello: (who: string): QueryKey => keys.segment('hello', who),
} as const;
