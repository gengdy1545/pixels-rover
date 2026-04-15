import { post } from '../client';

export const queryApi = {
  submitQuery: (data: { sql: string; schemaName: string }) =>
    post<unknown>('/api/v1/query/submit-query', data),

  getQueryStatus: (queryId: string) =>
    post<unknown>('/api/v1/query/get-query-status', { queryId }),

  getQueryResult: (queryId: string) =>
    post<unknown>('/api/v1/query/get-query-result', { queryId }),
};
