/**
 * `features/schema` barrel——frontend.md §2 纪律 3 指定的唯一跨 feature
 * 入口。
 *
 * 对外只暴露：
 *   - React hooks（`useBackendsQuery` / `useSchemasQuery` / ...）——
 *     组件层的真正消费面；
 *   - `schemaKeys` 工厂——让 auth 登出 / 用户切换后台等场景的 cross-feature
 *     `invalidateQueries` 有一个合法的 key 句柄；
 * 不暴露：
 *   - `hooks/` / `model/` / `services/` 内部文件——任何 `@/features/schema/
 *     hooks/useSchemaQueries` 这种穿透路径都会被 lint-0 拦截。
 */

export {
  useBackendsQuery,
  useSchemasQuery,
  useTablesQuery,
  useColumnsQuery,
} from './hooks/useSchemaQueries';

export { schemaKeys } from './model/queryKeys';
