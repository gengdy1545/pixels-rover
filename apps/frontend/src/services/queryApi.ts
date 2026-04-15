import api from './api';
import type { ApiResponse } from '../types/api';

export const queryApi = {
  submitQuery: (data: { sql: string; schemaName: string }) =>
    api.post<ApiResponse<unknown>>('/api/v1/query/submit-query', data),

  getQueryStatus: (queryId: string) =>
    api.post<ApiResponse<unknown>>('/api/v1/query/get-query-status', { queryId }),

  getQueryResult: (queryId: string) =>
    api.post<ApiResponse<unknown>>('/api/v1/query/get-query-result', { queryId }),
};
