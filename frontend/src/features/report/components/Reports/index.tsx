import React, { useEffect, useMemo, useState } from 'react';
import { DatePicker, Button, Card, Row, Col, message } from 'antd';
import ReactECharts from 'echarts-for-react';
import dayjs from 'dayjs';
// `conversationApi` 走 conversation feature 的 barrel escape hatch（见
// `features/conversation/index.ts` 注释）：Reports 当前需要 N-thread
// aggregate（`Promise.all(map(getConversation))`），未来用 `useQueries`
// 重写后这条 import 可以撤回为常规 `useThreadsQuery` + per-thread query。
import { conversationApi } from '../../../conversation';
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
  const [runs, setRuns] = useState<ReportRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);

  useEffect(() => {
    void loadRuns();
  }, []);

  const loadRuns = async () => {
    setLoading(true);
    try {
      const threads = await conversationApi.listConversations();
      const details = await Promise.all(
        threads.map((thread) => conversationApi.getConversation(thread.threadId)),
      );

      const nextRuns = flattenRuns(
        threads,
        details.map((detail) => detail.history),
      );
      setRuns(nextRuns);
    } catch {
      message.error('Failed to load reports');
    } finally {
      setLoading(false);
    }
  };

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
            value: filteredRuns.filter((run) => run.status === 'completed' || run.status === 'partial').length,
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
        <Button type="primary" onClick={loadRuns} loading={loading}>
          Refresh
        </Button>
        <Button onClick={() => setDateRange(null)} disabled={!dateRange}>
          Reset
        </Button>
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
                  {run.createdAt ? new Date(run.createdAt).toLocaleString() : 'Unknown time'}
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
      const sqlSteps = item.stepResults.filter((step) => step.action === 'generate_and_execute_sql');
      const totalRows = sqlSteps.reduce((sum, step) => sum + (step.result?.row_count || 0), 0);

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
