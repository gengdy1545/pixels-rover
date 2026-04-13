import api from './api';
import type { ApiResponse } from '../types/api';
import type { MessageDetail, QueryResult } from '../types/query';

export const chatApi = {
  textToSql: (data: { question: string; schemaName: string; tables: string[]; columns: Record<string, string[]> }) =>
    api.post<ApiResponse<unknown>>('/api/v1/query/text-to-sql', data),

  saveSql: (uuid: string, sqlText: string) =>
    api.post<ApiResponse<void>>('/api/v1/chat/save-sql', { uuid, sqlText }),

  updateSql: (uuid: string, newSQL: string) =>
    api.put<ApiResponse<void>>('/api/v1/chat/update-sql', { uuid, newSQL }),

  getSql: (uuid: string) =>
    api.post<ApiResponse<string>>('/api/v1/chat/get-sql', { uuid }),

  saveMessage: (uuid: string, sqlText: string, userMessage: string, userMessageUuid: string) =>
    api.post<ApiResponse<void>>('/api/v1/chat/save-message', { uuid, sqlText, userMessage, userMessageUuid }),

  saveQueryResult: (uuid: string, result: string, resultLimit: number, resultUuid: string) =>
    api.post<ApiResponse<void>>('/api/v1/chat/save-query-result', { uuid, result, resultLimit, resultUuid }),

  getChatHistory: () =>
    api.get<ApiResponse<MessageDetail[]>>('/api/v1/chat/history'),

  getQueryResults: () =>
    api.get<ApiResponse<QueryResult[]>>('/api/v1/chat/query-results'),

  getQueryResultsBetween: (startTime: string, endTime: string) =>
    api.post<ApiResponse<QueryResult[]>>('/api/v1/chat/query-results-between', { startTime, endTime }),
};
