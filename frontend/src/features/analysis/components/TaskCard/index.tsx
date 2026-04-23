import React from 'react';
import { Card, Descriptions, Tag, Progress } from 'antd';
import { AimOutlined } from '@ant-design/icons';
import type { AnalysisTask } from '../../../../shared/types/analysis';

interface TaskCardProps {
  task: AnalysisTask;
}

const taskTypeLabels: Record<string, { label: string; color: string }> = {
  query: { label: '单指标查询', color: 'blue' },
  compare: { label: '多维对比', color: 'orange' },
  diagnose: { label: '归因诊断', color: 'red' },
};

const TaskCard: React.FC<TaskCardProps> = ({ task }) => {
  const typeInfo = taskTypeLabels[task.task_type] || { label: task.task_type, color: 'default' };
  const confidencePercent = Math.round(task.confidence * 100);

  return (
    <Card
      size="small"
      title={
        <span>
          <AimOutlined style={{ marginRight: 8 }} />
          任务理解
        </span>
      }
      style={{ marginBottom: 16 }}
    >
      <Descriptions size="small" column={2}>
        <Descriptions.Item label="任务类型">
          <Tag color={typeInfo.color}>{typeInfo.label}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="置信度">
          <Progress
            percent={confidencePercent}
            size="small"
            style={{ width: 120 }}
            status={confidencePercent >= 80 ? 'success' : confidencePercent >= 50 ? 'normal' : 'exception'}
          />
        </Descriptions.Item>
        <Descriptions.Item label="目标指标">
          {task.target_metrics.map((m) => (
            <Tag key={m} color="processing">{m}</Tag>
          ))}
        </Descriptions.Item>
        {task.time_range && (
          <Descriptions.Item label="时间范围">
            <Tag>{task.time_range.description || task.time_range.preset || '未指定'}</Tag>
          </Descriptions.Item>
        )}
        {task.filters.length > 0 && (
          <Descriptions.Item label="过滤条件" span={2}>
            {task.filters.map((f, i) => (
              <Tag key={i}>
                {f.dimension} {f.operator} {Array.isArray(f.value) ? f.value.join(', ') : f.value}
              </Tag>
            ))}
          </Descriptions.Item>
        )}
        {task.comparison_baseline && (
          <Descriptions.Item label="对比基线">
            <Tag color="volcano">
              {task.comparison_baseline.description || task.comparison_baseline.preset || '基线'}
            </Tag>
          </Descriptions.Item>
        )}
        {task.analysis_dimensions.length > 0 && (
          <Descriptions.Item label="分析维度">
            {task.analysis_dimensions.map((d) => (
              <Tag key={d}>{d}</Tag>
            ))}
          </Descriptions.Item>
        )}
      </Descriptions>
    </Card>
  );
};

export default TaskCard;
