import React from 'react';
import { Steps, Card } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons';
import type { PlanStep, StepStatus } from '../../shared/types/analysis';

interface PlanTimelineProps {
  steps: PlanStep[];
  explanation?: string;
  onStepClick?: (stepId: string) => void;
}

const statusConfig: Record<StepStatus, { icon: React.ReactNode; status: 'finish' | 'process' | 'error' | 'wait' }> = {
  completed: { icon: <CheckCircleOutlined />, status: 'finish' },
  running: { icon: <LoadingOutlined />, status: 'process' },
  failed: { icon: <CloseCircleOutlined />, status: 'error' },
  pending: { icon: <ClockCircleOutlined />, status: 'wait' },
  skipped: { icon: <MinusCircleOutlined />, status: 'wait' },
};

const PlanTimeline: React.FC<PlanTimelineProps> = ({ steps, explanation, onStepClick }) => {
  const currentIndex = steps.findIndex((s) => s.status === 'running');

  return (
    <Card
      size="small"
      title="执行计划"
      extra={explanation && <span style={{ color: '#8c8c8c', fontSize: 12 }}>{explanation}</span>}
      style={{ marginBottom: 16 }}
    >
      <Steps
        direction="vertical"
        size="small"
        current={currentIndex >= 0 ? currentIndex : undefined}
        items={steps.map((step) => {
          const config = statusConfig[step.status];
          const durationText = step.duration_ms != null ? `${step.duration_ms}ms` : '';
          return {
            title: (
              <span
                onClick={() => onStepClick?.(step.step_id)}
                style={{ cursor: onStepClick ? 'pointer' : 'default' }}
              >
                <strong>{step.step_id}</strong> {step.description}
              </span>
            ),
            description: (
              <span style={{ fontSize: 12 }}>
                {step.status === 'failed' && step.error && (
                  <span style={{ color: '#ff4d4f' }}>{step.error}</span>
                )}
                {step.status === 'completed' && durationText && (
                  <span style={{ color: '#52c41a' }}>{durationText}</span>
                )}
                {step.status === 'running' && (
                  <span style={{ color: '#1890ff' }}>执行中...</span>
                )}
              </span>
            ),
            icon: config.icon,
            status: config.status,
          };
        })}
      />
    </Card>
  );
};

export default PlanTimeline;
