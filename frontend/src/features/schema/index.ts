/**
 * `features/schema` barrel——frontend.md §2 纪律 3 指定的唯一跨 feature 入口。
 *
 * 对外暴露：
 *   - 元数据 hooks（`useBackendsQuery` / `useSchemasQuery` / `useTablesQuery`
 *     / `useColumnsQuery`）——分析侧 / 报表侧需要"哪些 backend / schema /
 *     table / column 可用"时的真正消费面；
 *   - `schemaKeys` 工厂——auth 登出 / 用户切换后台等场景跨 feature
 *     `invalidateQueries` 时拿到合法 key 句柄；
 *   - `SchemaBrowser` 组件——侧栏的 schema 树；Sidebar shell 通过 barrel
 *     消费（不穿透 `@/features/schema/components/*`，符合 lint-0 精神）。
 *
 * 不暴露：
 *   - `metadataApi`——feature 私有 API 客户端；其它代码读元数据请走
 *     hooks，hooks 把 query key 与缓存策略封死，避免野调。
 *   - `hooks/` / `model/` / `services/` / `components/` 内部文件——任何
 *     `@/features/schema/<sub>/<file>` 这种穿透路径都会被 lint-0 拦截。
 */

export {
  useBackendsQuery,
  useSchemasQuery,
  useTablesQuery,
  useColumnsQuery,
} from './hooks/useSchemaQueries';

export { schemaKeys } from './model/queryKeys';

export { default as SchemaBrowser } from './components/SchemaBrowser';
