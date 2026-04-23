/**
 * Analysis 页——analysis feature 的顶层视图（Stage 3 §10 PR-4 从
 * `pages/Analysis/` 迁入）。
 *
 * 这一层只负责"把 in-flight store 状态拼成可视化布局"：状态从
 * `useAnalysisStore` 拿、可用指标列表从 `features/semantic` 的
 * `useSemanticMetricsQuery` 拿、各子卡片是 feature 自有 components。
 *
 * 受 Home 编排：
 *   - `currentThread` 来自 Home（URL → useThreadsQuery 派生）；为空时
 *     渲染"先建对话"占位 + 调 `onCreateConversation` 回调；
 *   - SSE 编排不在这里——`startAnalysis` 把 SSE 生命周期收在 store 里，
 *     这里只 dispatch 一个用户问题。
 *
 * 为什么 Analysis 留在 `features/analysis/components/Analysis/` 而不进
 * `app/pages/`：Login / Register / Reports 的迁位都是同一规则——单
 * feature 的页面随 feature 走；只有跨 feature shell（Home）才挂在
 * `pages/` 顶层。barrel 只暴露 lazy-wrapped 的 `Analysis`，让 Home
 * 继续通过 `React.lazy(() => import('@/features/analysis'))` 实现 chunk
 * 分割。
 */

import React, { useEffect, useRef } from 'react';
import { Alert, Button, Empty, Spin, Space, Typography } from 'antd';
import {
  RocketOutlined,
  CheckCircleFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
  SyncOutlined,
} from '@ant-design/icons';
import AnalysisInput from '../AnalysisInput';
import TaskCard from '../TaskCard';
import PlanTimeline from '../PlanTimeline';
import StepDetail from '../StepDetail';
import SummaryCard from '../SummaryCard';
import { useAnalysisStore } from '../../model/store';
import { useSemanticMetricsQuery } from '../../../semantic';
import type { SessionStatus } from '../../../../shared/types/analysis';
import type { ConversationThread } from '../../../../shared/types/conversation';
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
    reconnectInfo,
    startAnalysis,
    reset,
  } = useAnalysisStore();

  const { data: availableMetrics = [] } = useSemanticMetricsQuery();

  const resultRef = useRef<HTMLDivElement>(null);

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

      {reconnectInfo && (
        <Alert
          type="warning"
          showIcon
          icon={<SyncOutlined spin />}
          message={
            reconnectInfo.reason === 'upstream'
              ? '分析服务暂时不稳，正在重试…'
              : `网络连接中断，正在重试 (${reconnectInfo.attempt}/${reconnectInfo.maxAttempts})…`
          }
          style={{ marginTop: 12 }}
        />
      )}

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
