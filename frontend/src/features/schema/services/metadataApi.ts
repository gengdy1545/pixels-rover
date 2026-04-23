/**
 * schema feature 的 API 客户端封装（Stage 3 §10 PR-3 从 shared/api/modules 迁入）。
 *
 * 归属判断（frontend.md §2 纪律 3 / §1.1.1）：
 *   - 这些 endpoint（`/api/v1/analysis/backends/...`）虽然 URL 前缀挂在
 *     analysis 命名空间下，但语义是**元数据导览**——backends 列表、schema
 *     列表、tables、columns。schema feature 是元数据导览的唯一消费者
 *     （SchemaBrowser 组件 + features/schema/hooks 都在本 feature 内）。
 *   - 后端的 URL 命名跟前端 feature 边界并不要 1:1 对齐：assistant-service
 *     选择把 metadata 接口挂在 analysis 路由树下是出于服务端方便，前端
 *     按消费侧聚合到 schema feature 是出于"谁拥有 UI 谁拥有 endpoint
 *     wrapper"的原则。
 *
 * 刻意不从 barrel 对外 re-export：唯一需要 backends/schemas/tables/columns
 * 数据的入口是本 feature 提供的 hooks（`useBackendsQuery` 等）。其它
 * feature 想要这些信息，请走 hooks 而不是直接调 API client——hooks 已经
 * 把 query key / 缓存策略 / loading 边界全都封死。
 */

import { get } from '../../../shared/api/client';
import type {
  BackendInfo,
  TableInfo,
  ColumnInfo,
} from '../../../shared/types/analysis';

export const metadataApi = {
  getBackends: (): Promise<BackendInfo[]> =>
    get<BackendInfo[]>('/api/v1/analysis/backends'),

  getSchemas: (backendId: string): Promise<string[]> =>
    get<{ schemas: string[] }>(
      `/api/v1/analysis/backends/${backendId}/schemas`,
    ).then((data) => data.schemas),

  getTables: (backendId: string, schema: string): Promise<TableInfo[]> =>
    get<{ tables: TableInfo[] }>(
      `/api/v1/analysis/backends/${backendId}/schemas/${schema}/tables`,
    ).then((data) => data.tables),

  getColumns: (
    backendId: string,
    schema: string,
    tableName: string,
  ): Promise<ColumnInfo[]> =>
    get<{ columns: ColumnInfo[] }>(
      `/api/v1/analysis/backends/${backendId}/schemas/${schema}/tables/${tableName}/columns`,
    ).then((data) => data.columns),
};
