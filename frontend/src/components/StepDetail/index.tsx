import React from 'react';
import { Collapse, Table, Tag, Empty } from 'antd';
import { CodeOutlined, TableOutlined } from '@ant-design/icons';
import CodeMirror from '@uiw/react-codemirror';
import { sql } from '@codemirror/lang-sql';
import type { PlanStep } from '../../types/analysis';

interface StepDetailProps {
  steps: PlanStep[];
}

const StepDetail: React.FC<StepDetailProps> = ({ steps }) => {
  const sqlSteps = steps.filter(
    (s) => s.action === 'generate_and_execute_sql' && (s.status === 'completed' || s.status === 'failed'),
  );

  if (sqlSteps.length === 0) return null;

  const items = sqlSteps.map((step) => {
    const resultColumns =
      step.result?.columns.map((col) => ({
        title: col,
        dataIndex: col,
        key: col,
        ellipsis: true,
        width: 150,
      })) || [];

    const resultData =
      step.result?.rows.map((row, idx) => {
        const obj: Record<string, unknown> = { key: idx };
        step.result?.columns.forEach((col, ci) => {
          obj[col] = row[ci];
        });
        return obj;
      }) || [];

    return {
      key: step.step_id,
      label: (
        <span>
          <Tag color={step.status === 'completed' ? 'success' : 'error'}>
            {step.step_id}
          </Tag>
          {step.description}
          {step.result?.row_count != null && (
            <Tag style={{ marginLeft: 8 }}>{step.result.row_count} 行</Tag>
          )}
          {step.duration_ms != null && (
            <Tag style={{ marginLeft: 4 }}>{step.duration_ms}ms</Tag>
          )}
        </span>
      ),
      children: (
        <div>
          {step.result?.sql && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ marginBottom: 4, color: '#8c8c8c', fontSize: 12 }}>
                <CodeOutlined /> SQL
              </div>
              <CodeMirror
                value={step.result.sql}
                extensions={[sql()]}
                editable={false}
                basicSetup={{ lineNumbers: true, foldGutter: false }}
                height="auto"
                minHeight="36px"
                maxHeight="160px"
              />
            </div>
          )}

          {step.status === 'failed' && step.error && (
            <div style={{ color: '#ff4d4f', marginBottom: 12 }}>
              错误：{step.error}
            </div>
          )}

          {resultColumns.length > 0 && resultData.length > 0 ? (
            <div>
              <div style={{ marginBottom: 4, color: '#8c8c8c', fontSize: 12 }}>
                <TableOutlined /> 查询结果
              </div>
              <Table
                columns={resultColumns}
                dataSource={resultData}
                size="small"
                scroll={{ x: 'max-content', y: 200 }}
                pagination={false}
              />
            </div>
          ) : step.status === 'completed' && step.result?.row_count === 0 ? (
            <Empty description="查询结果为空" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : null}
        </div>
      ),
    };
  });

  return (
    <Collapse
      size="small"
      items={items}
      style={{ marginBottom: 16 }}
    />
  );
};

export default StepDetail;
