import api from './api';
import type { BackendInfo, TableInfo, ColumnInfo } from '../types/analysis';

export const metadataApi = {
  getBackends: () =>
    api.get<BackendInfo[]>('/api/v1/backends'),

  getSchemas: (backendId: string) =>
    api.get<{ schemas: string[] }>(`/api/v1/backends/${backendId}/schemas`),

  getTables: (backendId: string, schema: string) =>
    api.get<{ tables: TableInfo[] }>(`/api/v1/backends/${backendId}/schemas/${schema}/tables`),

  getColumns: (backendId: string, schema: string, tableName: string) =>
    api.get<{ columns: ColumnInfo[] }>(
      `/api/v1/backends/${backendId}/schemas/${schema}/tables/${tableName}/columns`,
    ),
};
