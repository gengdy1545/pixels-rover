export interface MessageDetail {
  userMessage: string;
  userMessageUuid: string;
  sqlText: string;
  sqlStatementsUuid: string;
  isExecuted: boolean;
  results: string | null;
  resultsLimit: number | null;
  resultsUuid: string | null;
}

export interface QueryResult {
  id: number;
  sqlStatementsUuid: string;
  result: string;
  resultLimit: number;
  resultUuid: string;
  createTime: string;
}

export interface TextToSQLRequest {
  question: string;
  schemaName: string;
  tables: string[];
  columns: Record<string, string[]>;
}

export interface TextToSQLResponse {
  sql: string;
}

export interface SubmitQueryRequest {
  sql: string;
  schemaName: string;
}

export interface SubmitQueryResponse {
  queryId: string;
  errorCode: number;
  errorMessage: string;
}

export interface GetQueryStatusRequest {
  queryId: string;
}

export interface GetQueryResultRequest {
  queryId: string;
}
