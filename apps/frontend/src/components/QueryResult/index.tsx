import React from 'react';
import { Table, Empty } from 'antd';
import type { ColumnsType } from 'antd/es/table';

interface QueryResultProps {
  columns: string[];
  rows: Record<string, unknown>[];
  loading?: boolean;
}

const QueryResult: React.FC<QueryResultProps> = ({ columns, rows, loading = false }) => {
  if (columns.length === 0) {
    return <Empty description="No query results" />;
  }

  const tableColumns: ColumnsType<Record<string, unknown>> = columns.map((col) => ({
    title: col,
    dataIndex: col,
    key: col,
    ellipsis: true,
    width: 150,
  }));

  return (
    <Table
      columns={tableColumns}
      dataSource={rows.map((row, idx) => ({ ...row, key: idx }))}
      size="small"
      loading={loading}
      scroll={{ x: 'max-content', y: 400 }}
      pagination={{
        pageSize: 50,
        showSizeChanger: true,
        pageSizeOptions: ['20', '50', '100'],
        showTotal: (total) => `Total ${total} rows`,
      }}
    />
  );
};

export default QueryResult;
