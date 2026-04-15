import { get, post, putVoid, postVoid } from '../client';
import type { MessageDetail, QueryResult } from '../../types/query';

export const chatApi = {
  textToSql: (data: { question: string; schemaName: string; tables: string[]; columns: Record<string, string[]> }) =>
    post<unknown>('/api/v1/query/text-to-sql', data),

  saveSql: (uuid: string, sqlText: string) =>
    postVoid('/api/v1/chat/save-sql', { uuid, sqlText }),

  updateSql: (uuid: string, newSQL: string) =>
    putVoid('/api/v1/chat/update-sql', { uuid, newSQL }),

  getSql: (uuid: string) =>
    post<string>('/api/v1/chat/get-sql', { uuid }),

  saveMessage: (uuid: string, sqlText: string, userMessage: string, userMessageUuid: string) =>
    postVoid('/api/v1/chat/save-message', { uuid, sqlText, userMessage, userMessageUuid }),

  saveQueryResult: (uuid: string, result: string, resultLimit: number, resultUuid: string) =>
    postVoid('/api/v1/chat/save-query-result', { uuid, result, resultLimit, resultUuid }),

  getChatHistory: () =>
    get<MessageDetail[]>('/api/v1/chat/history'),

  getQueryResults: () =>
    get<QueryResult[]>('/api/v1/chat/query-results'),

  getQueryResultsBetween: (startTime: string, endTime: string) =>
    post<QueryResult[]>('/api/v1/chat/query-results-between', { startTime, endTime }),
};
