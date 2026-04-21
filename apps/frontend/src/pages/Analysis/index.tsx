import React, { useEffect, useRef } from 'react';
import { Button, Empty, Spin, Space, Typography } from 'antd';
import {
  RocketOutlined,
  CheckCircleFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
} from '@ant-design/icons';
import AnalysisInput from '../../components/AnalysisInput';
import TaskCard from '../../components/TaskCard';
import PlanTimeline from '../../components/PlanTimeline';
import StepDetail from '../../components/StepDetail';
import SummaryCard from '../../components/SummaryCard';
import { useAnalysisStore, type SessionStatus } from '../../stores/analysisStore';
import type { ConversationThread } from '../../types/conversation';
import './index.css';

const { Text, Title } = Typography;

interface AnalysisProps {
  currentThread: ConversationThread | null;
  onCreateConversation: () => void;
}

const statusLabels: Record<SessionStatus, { label: string; icon: React.ReactNode; color: string }> = {
  idle: { label: '', icon: null, color: '' },
  received: { label: '已接收', icon: <Spin size="small" />, color: '#1890ff' },
  understanding: { label: '正在理解问题...', icon: <Spin size="small" />, color: '#1890ff' },
  resolving: { label: '正在解析语义...', icon: <Spin size="small" />, color: '#722ed1' },
  planning: { label: '正在规划执行方案...', icon: <Spin size="small" />, color: '#faad14' },
  executing: { label: '正在执行查询...', icon: <Spin size="small" />, color: '#13c2c2' },
  summarizing: { label: '正在生成结论...', icon: <Spin size="small" />, color: '#eb2f96' },
  completed: { label: '分析完成', icon: <CheckCircleFilled />, color: '#52c41a' },
  partial: { label: '部分完成', icon: <ExclamationCircleFilled />, color: '#faad14' },
  failed: { label: '分析失败', icon: <ExclamationCircleFilled />, color: '#ff4d4f' },
  cancelled: { label: '分析已取消', icon: <ExclamationCircleFilled />, color: '#8c8c8c' },
  clarification_needed: { label: '需要补充信息', icon: <InfoCircleFilled />, color: '#1890ff' },
};

const Analysis: React.FC<AnalysisProps> = ({ currentThread, onCreateConversation }) => {
  const {
    threadId,
    status,
    task,
    plan,
    steps,
    summary,
    warnings,
    error,
    isLoading,
    availableMetrics,
    startAnalysis,
    reset,
    loadMetrics,
  } = useAnalysisStore();

  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadMetrics();
  }, []);

  useEffect(() => {
    if (status === 'completed' || status === 'partial' || status === 'failed') {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [status]);

  const handleSubmit = (question: string) => {
    if (!currentThread) {
      return;
    }
    reset();
    startAnalysis(question, currentThread.threadId);
  };

  const statusInfo = statusLabels[status];
  const showResults = status !== 'idle';

  return (
    <div className="analysis-page">
      <div className="analysis-header">
        <Title level={4} style={{ margin: 0 }}>
          <RocketOutlined style={{ marginRight: 8 }} />
          智能分析
        </Title>
      </div>

      {currentThread ? (
        <div className="analysis-context">
          <Text strong>{currentThread.title}</Text>
          <Text type="secondary">
            Backend `{currentThread.backendId}`
            {currentThread.schemaName ? ` / Schema \`${currentThread.schemaName}\`` : ''}
          </Text>
        </div>
      ) : (
        <Empty description="先创建一个对话线程，再开始新的分析。">
          <Button type="primary" onClick={onCreateConversation}>
            新建对话
          </Button>
        </Empty>
      )}

      <AnalysisInput
        onSubmit={handleSubmit}
        loading={isLoading}
        availableMetrics={availableMetrics}
        disabled={!threadId}
      />

      {showResults && (
        <div className="analysis-results" ref={resultRef}>
          {statusInfo.label && (
            <div className="status-bar" style={{ borderLeftColor: statusInfo.color }}>
              <Space>
                {statusInfo.icon}
                <Text strong style={{ color: statusInfo.color }}>
                  {statusInfo.label}
                </Text>
              </Space>
            </div>
          )}

          {task && <TaskCard task={task} />}

          {plan && steps.length > 0 && (
            <PlanTimeline steps={steps} explanation={plan.explanation} />
          )}

          {steps.length > 0 && <StepDetail steps={steps} />}

          <SummaryCard
            summary={summary}
            warnings={warnings}
            error={error}
            status={status}
          />
        </div>
      )}
    </div>
  );
};

export default Analysis;
