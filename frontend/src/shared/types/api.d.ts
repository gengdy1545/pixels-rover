// Unified API response type
export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data?: T;
  errorCode?: string;
  requestId?: string;
  apiVersion?: string;
}

// Stable cross-service error codes
export type ErrorCode =
  | 'INVALID_ARGUMENT'
  | 'AUTHENTICATION_REQUIRED'
  | 'INVALID_CREDENTIALS'
  | 'INVALID_TOKEN'
  | 'INVALID_TOKEN_TYPE'
  | 'ACCESS_DENIED'
  | 'RESOURCE_NOT_FOUND'
  | 'METHOD_NOT_ALLOWED'
  | 'RESOURCE_CONFLICT'
  | 'DEPENDENCY_ERROR'
  | 'INTERNAL_ERROR';

// Pagination
export interface PageParams {
  page: number;
  pageSize: number;
}
