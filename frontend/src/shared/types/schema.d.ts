/**
 * Schema / table / column metadata returned by `assistant-service`'s
 * semantic-layer endpoints (GET /api/v1/semantic/schemas, /tables, /columns).
 *
 * owning-service: assistant-service
 * source-of-truth: services/assistant-service/openapi.json#/components/schemas/
 *   — Schema / Table / Column / GetSchemasRequest / GetTablesRequest /
 *     GetColumnsRequest (generated from the matching pydantic models in
 *     services/assistant-service/app/schemas/semantic.py).
 *
 * Hand-mirrored per frontend.md §4.6 "手写契约镜像文件的顶部元数据" rule;
 * any field addition needs a paired assistant-service OpenAPI change.
 */
export interface Schema {
  name: string;
}

export interface Table {
  name: string;
  type: string;
}

export interface Column {
  name: string;
  type: string;
}

export interface GetSchemasRequest {
  // empty for now
}

export interface GetTablesRequest {
  schemaName: string;
}

export interface GetColumnsRequest {
  schemaName: string;
  tableName: string;
}
