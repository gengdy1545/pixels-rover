import api from './api';
import type { ApiResponse } from '../types/api';

export const metadataApi = {
  getSchemas: () =>
    api.post<ApiResponse<unknown>>('/api/v1/metadata/get-schemas', {}),

  getTables: (schemaName: string) =>
    api.post<ApiResponse<unknown>>('/api/v1/metadata/get-tables', { schemaName }),

  getColumns: (schemaName: string, tableName: string) =>
    api.post<ApiResponse<unknown>>('/api/v1/metadata/get-columns', { schemaName, tableName }),

  getViews: (schemaName: string) =>
    api.post<ApiResponse<unknown>>('/api/v1/metadata/get-views', { schemaName }),
};
