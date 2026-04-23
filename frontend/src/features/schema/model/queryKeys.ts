/**
 * schema feature 的 TanStack query key 定义（C1 决策）。
 *
 * 文件落在 `features/schema/model/`——lint-1 禁 react / react-router-dom /
 * antd；因此这里只定义 key **构造器**，不写 hook；`useBackendsQuery` 等
 * useQuery 组合在 `features/schema/hooks/` 下。
 *
 * 分层语义：
 *   - `all` —— 整张 feature 的失效根，用于 "登出后清空整站缓存" 之类的
 *     全量 invalidate。
 *   - `backends()` —— backends 列表（每个 user 登录态只对应一份；不做
 *     filter 切片）。
 *   - `schemasByBackend(backendId)` —— 某 backend 下的 schema 名单；缓存
 *     可以 per-backendId 分片失效。
 *   - `tablesByBackendAndSchema(backendId, schema)` —— 进一步下钻。
 *   - `columnsByTable(backendId, schema, table)` —— 最细粒度；当前 UI
 *     没用但保留接口完整性，后续 Stage 3 搬 Schema 详情页时直接消费。
 *
 * 刻意把 `backendId` / `schema` / `table` 作为独立 segment 并列放进 key，
 * 而非拼成 `"b1/s1/t1"` 字符串：
 *   - TanStack `invalidateQueries({ queryKey: schemaKeys.tablesByBackendAndSchema(b,s) })`
 *     在不提供 `exact: true` 的情况下会前缀匹配——使得
 *     "invalidate backend b1 下所有 schema 的 tables" 直接变成
 *     `invalidateQueries({ queryKey: [...schemaKeys.all, 'tables', b1] })`
 *     这种自然前缀语义；字符串拼接会把前缀匹配退化成全字符串相等。
 */

import {
  createFeatureKeyFactory,
  type QueryKey,
} from '../../../shared/types/query-keys';

const keys = createFeatureKeyFactory('schema');

export const schemaKeys = {
  all: keys.all(),
  backends: (): QueryKey => keys.segment('backends'),
  schemasByBackend: (backendId: string): QueryKey =>
    keys.segment('schemas', backendId),
  tablesByBackendAndSchema: (backendId: string, schemaName: string): QueryKey =>
    keys.segment('tables', backendId, schemaName),
  columnsByTable: (
    backendId: string,
    schemaName: string,
    tableName: string,
  ): QueryKey => keys.segment('columns', backendId, schemaName, tableName),
} as const;
