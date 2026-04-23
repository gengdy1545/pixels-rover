/**
 * schema feature 的 React Query hooks 层。
 *
 * 责任划分（对齐 `frontend.md §2`）：
 *   - hooks/ 层：组装 `shared/api` 的 Promise-returning 函数 + `model/`
 *     的 query key 工厂 + `@tanstack/react-query` 的 `useQuery`；是
 *     feature 对外暴露**给组件**的消费面。
 *   - 禁止向下反依赖 `components/`；禁止被 `model/` 反过来 import
 *     （lint-1）。
 *
 * 缓存策略决策（对齐 `QueryClient` 默认值，见
 * `app/providers/QueryClientProvider.tsx`）：
 *   - backends / schemas / tables / columns 都是"不会频繁变"的元数据
 *     类查询，沿用 QueryClient 默认 `staleTime=30s` / `gcTime=5min`；不
 *     在 hook 层硬编 override，留给未来如果确实需要长缓存的单独接入点
 *     再调。
 *   - `tables` / `columns` 查询依赖 backendId+schema 同时非空，所以用
 *     `enabled` 开关把未就绪的 fetch 挡在外面；组件侧直接传原始值，不需
 *     要自己写 `if (backendId) fetch(...)` 的条件分支。
 */

import { useQuery } from '@tanstack/react-query';
import { metadataApi } from '../services/metadataApi';
import { schemaKeys } from '../model/queryKeys';

export function useBackendsQuery() {
  return useQuery({
    queryKey: schemaKeys.backends(),
    queryFn: () => metadataApi.getBackends(),
  });
}

export function useSchemasQuery(backendId: string | null) {
  return useQuery({
    queryKey: schemaKeys.schemasByBackend(backendId ?? ''),
    queryFn: () => metadataApi.getSchemas(backendId as string),
    enabled: !!backendId,
  });
}

export function useTablesQuery(
  backendId: string | null,
  schemaName: string | null,
) {
  return useQuery({
    queryKey: schemaKeys.tablesByBackendAndSchema(
      backendId ?? '',
      schemaName ?? '',
    ),
    queryFn: () =>
      metadataApi.getTables(backendId as string, schemaName as string),
    enabled: !!backendId && !!schemaName,
  });
}

export function useColumnsQuery(
  backendId: string | null,
  schemaName: string | null,
  tableName: string | null,
) {
  return useQuery({
    queryKey: schemaKeys.columnsByTable(
      backendId ?? '',
      schemaName ?? '',
      tableName ?? '',
    ),
    queryFn: () =>
      metadataApi.getColumns(
        backendId as string,
        schemaName as string,
        tableName as string,
      ),
    enabled: !!backendId && !!schemaName && !!tableName,
  });
}
