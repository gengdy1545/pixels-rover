/**
 * Reports 页——对历史 analysis run 做聚合。
 *
 * **为什么用 `useQueries` 而不是手写 `Promise.all`**（frontend.md §4.5 +
 * §1.1.1 硬规则的一致应用）：
 *
 *   - `useQueries` 走的是同一份 `detail(threadId)` 缓存——Home 页消费
 *     `useConversationQuery` 的那份。切 threads → Reports → threads 的
 *     往返只会命中 cache，不会各自重新 `getConversation` 一次；而原版用
 *     `Promise.all(map(getConversation))` 每进一次 Reports 都把后端打一
 *     遍，页内切换 filter 也触发完整重拉（setState 重渲染的副作用）。
 *   - `useQueries` 的每条子 query 独立 retry / inFlight，单 thread 的
 *     detail 拉取失败不会把整个 Reports 拖成"全灰一片 + message.error"；
 *     原版一次 `Promise.all` 中途任一 thread 失败就整个 try/catch 走
 *     message.error，用户只能盲点 Refresh 再赌一遍。
 *   - 用 hooks 代替 escape hatch 后，`features/conversation` 的 barrel 不
 *     再向 `conversationApi`（私有 service 客户端）透口子；这是 Stage 3
 *     §10 PR-3 留下的尾余，完成后 barrel 回归"只暴露 hooks + keys + 组
 *     件"的干净形态，`services/` 对外彻底私有。
 *
 * 不改的动作（故意列出来防止回潮）：
 *
 *   - 日期 filter / chart option 形态保持原状——用户可见行为不变；
 *   - 空 thread 列表（首次登录）仍展示 "No analysis runs available"，不
 *     做 loading 骨架——Reports 入口本来就隐在侧栏深层，骨架反而抢焦点；
 *   - 不在这里写 thread-level cache invalidation——跨 feature 失效由
 *     conversation feature 自己的 mutation hooks 驱动，Reports 只订阅读。
 */

import React, { useMemo, useState } from 'react';
import { DatePicker, Button, Card, Row, Col, message } from 'antd';
import ReactECharts from 'echarts-for-react';
import dayjs from 'dayjs';
import {
  useConversationDetailsQueries,
  useThreadsQuery,
} from '../../../conversation';
import type {
  ConversationHistoryItem,
  ConversationThread,
} from '../../../../shared/types/conversation';
import './index.css';

const { RangePicker } = DatePicker;

interface ReportRun {
  sessionId: string;
  threadId: string;
  threadTitle: string;
  question: string;
  status: string;
  createdAt: string | null;
  sqlExecutions: number;
  totalRows: number;
}

const Reports: React.FC = () => {
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);

  const threadsQuery = useThreadsQuery();
  const threads = threadsQuery.data ?? [];

  // Shares the same `detail(threadId)` cache that Home page's
  // `useConversationQuery` uses, so cross-page navigation hits cache rather
  // than re-fetching every thread detail. Each sub-query fails / retries
  // independently: one broken thread does not wipe the whole report.
  const conversationQueries = useConversationDetailsQueries(
    threads.map((t) => t.threadId),
  );

  const isLoading =
    threadsQuery.isLoading ||
    conversationQueries.some((q) => q.isLoading);

  const threadsError = threadsQuery.isError;
  const anyDetailErrored = conversationQueries.some((q) => q.isError);

  // Surface a one-shot banner via antd message, mirroring the old fetch-time
  // toast. Deliberately only fires on hard failures (the threads list itself
  // or *all* per-thread details failed) to avoid spamming when a single
  // thread detail is down — that single thread just doesn't contribute rows.
  React.useEffect(() => {
    if (threadsError) {
      message.error('Failed to load reports');
    }
  }, [threadsError]);

  const runs = useMemo<ReportRun[]>(() => {
    const histories: ConversationHistoryItem[][] = threads.map((_, idx) => {
      const q = conversationQueries[idx];
      return q?.data?.history ?? [];
    });
    return flattenRuns(threads, histories);
  }, [threads, conversationQueries]);

  const filteredRuns = useMemo(() => {
    if (!dateRange) {
      return runs;
    }
    return runs.filter((run) => {
      if (!run.createdAt) {
        return false;
      }
      const createdAt = dayjs(run.createdAt);
      return (
        (createdAt.isAfter(dateRange[0]) || createdAt.isSame(dateRange[0])) &&
        (createdAt.isBefore(dateRange[1]) || createdAt.isSame(dateRange[1]))
      );
    });
  }, [dateRange, runs]);

  const handleRefresh = () => {
    // Force-refresh everything the page renders: both the thread list and
    // each per-thread detail. Using `refetch()` on each sub-query rather
    // than `queryClient.invalidateQueries()` keeps Reports self-contained —
    // cross-feature consumers (Home) on the same `detail(threadId)` key get
    // the fresh data for free via the shared cache.
    threadsQuery.refetch();
    conversationQueries.forEach((q) => q.refetch());
  };

  const overallChartOption = {
    title: { text: 'Overall Chart', left: 'center' },
    tooltip: { trigger: 'item' as const },
    series: [
      {
        type: 'pie',
        radius: '60%',
        data: [
          { value: filteredRuns.length, name: 'Total Runs' },
          {
            value: filteredRuns.filter(
              (run) => run.status === 'completed' || run.status === 'partial',
            ).length,
            name: 'Completed Runs',
          },
        ],
      },
    ],
  };

  const timeLabels = filteredRuns.map((run) =>
    run.createdAt ? new Date(run.createdAt).toLocaleDateString() : 'Unknown',
  );
  const uniqueDates = [...new Set(timeLabels)];
  const queryCounts = uniqueDates.map(
    (date) => timeLabels.filter((label) => label === date).length,
  );

  const timeChartOption = {
    title: { text: 'Time Chart', left: 'center' },
    tooltip: { trigger: 'axis' as const },
    xAxis: { type: 'category' as const, data: uniqueDates },
    yAxis: { type: 'value' as const },
    series: [
      {
        type: 'line',
        data: queryCounts,
        smooth: true,
        areaStyle: {},
      },
    ],
  };

  const costChartOption = {
    title: { text: 'Rows Chart', left: 'center' },
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: filteredRuns.map((_, index) => `Run ${index + 1}`),
    },
    yAxis: { type: 'value' as const, name: 'Rows Returned' },
    series: [
      {
        type: 'bar',
        data: filteredRuns.map((run) => run.totalRows),
        itemStyle: { color: '#1890ff' },
      },
    ],
  };

  return (
    <div className="reports-layout">
      <div className="reports-filter">
        <RangePicker
          value={dateRange}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setDateRange([dates[0], dates[1]]);
            } else {
              setDateRange(null);
            }
          }}
        />
        <Button type="primary" onClick={handleRefresh} loading={isLoading}>
          Refresh
        </Button>
        <Button onClick={() => setDateRange(null)} disabled={!dateRange}>
          Reset
        </Button>
        {anyDetailErrored && (
          <span className="reports-partial-hint">
            Some thread details failed to load; totals reflect successful threads only.
          </span>
        )}
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card>
            <ReactECharts option={overallChartOption} style={{ height: 300 }} />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card>
            <ReactECharts option={timeChartOption} style={{ height: 300 }} />
          </Card>
        </Col>
        <Col xs={24}>
          <Card>
            <ReactECharts option={costChartOption} style={{ height: 300 }} />
          </Card>
        </Col>
      </Row>

      <div className="query-info-section">
        <Card title="Run Details">
          <div className="query-info-list">
            {filteredRuns.map((run) => (
              <div key={run.sessionId} className="query-info-item">
                <span className="query-info-label">{run.threadTitle}</span>
                <span className="query-info-time">
                  {run.createdAt
                    ? new Date(run.createdAt).toLocaleString()
                    : 'Unknown time'}
                </span>
                <span className="query-info-limit">
                  {run.status} · SQL {run.sqlExecutions} · Rows {run.totalRows}
                </span>
              </div>
            ))}
            {filteredRuns.length === 0 && (
              <div className="no-data">No analysis runs available</div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};

function flattenRuns(
  threads: ConversationThread[],
  histories: ConversationHistoryItem[][],
): ReportRun[] {
  return threads.flatMap((thread, index) =>
    histories[index].map((item) => {
      const sqlSteps = item.stepResults.filter(
        (step) => step.action === 'generate_and_execute_sql',
      );
      const totalRows = sqlSteps.reduce(
        (sum, step) => sum + (step.result?.row_count || 0),
        0,
      );

      return {
        sessionId: item.sessionId,
        threadId: item.threadId,
        threadTitle: thread.title,
        question: item.question,
        status: item.status,
        createdAt: item.createdAt || null,
        sqlExecutions: item.stats.sqlExecutions || sqlSteps.length,
        totalRows,
      };
    }),
  );
}

export default Reports;
