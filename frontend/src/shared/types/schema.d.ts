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
