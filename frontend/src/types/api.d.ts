// Unified API response type
export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

// Pagination
export interface PageParams {
  page: number;
  pageSize: number;
}
