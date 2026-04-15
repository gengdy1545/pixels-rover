import { get } from '../client';
import type { BackendInfo, TableInfo, ColumnInfo } from '../../types/analysis';

export const metadataApi = {
  getBackends: (): Promise<BackendInfo[]> =>
    get<BackendInfo[]>('/api/v1/backends'),

  getSchemas: (backendId: string): Promise<string[]> =>
    get<{ schemas: string[] }>(`/api/v1/backends/${backendId}/schemas`)
      .then((data) => data.schemas),

  getTables: (backendId: string, schema: string): Promise<TableInfo[]> =>
    get<{ tables: TableInfo[] }>(`/api/v1/backends/${backendId}/schemas/${schema}/tables`)
      .then((data) => data.tables),

  getColumns: (backendId: string, schema: string, tableName: string): Promise<ColumnInfo[]> =>
    get<{ columns: ColumnInfo[] }>(`/api/v1/backends/${backendId}/schemas/${schema}/tables/${tableName}/columns`)
      .then((data) => data.columns),
};
