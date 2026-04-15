import React, { useState, useEffect } from 'react';
import { DatePicker, Button, Card, Row, Col, message } from 'antd';
import ReactECharts from 'echarts-for-react';
import { chatApi } from '../../api';
import type { QueryResult } from '../../types/query';
import dayjs from 'dayjs';
import './index.css';

const { RangePicker } = DatePicker;

const Reports: React.FC = () => {
  const [queryResults, setQueryResults] = useState<QueryResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);

  useEffect(() => {
    loadAllResults();
  }, []);

  const loadAllResults = async () => {
    setLoading(true);
    try {
      const results = await chatApi.getQueryResults();
      setQueryResults(results || []);
    } catch {
      message.error('Failed to load query results');
    } finally {
      setLoading(false);
    }
  };

  const loadFilteredResults = async () => {
    if (!dateRange) {
      loadAllResults();
      return;
    }
    setLoading(true);
    try {
      const results = await chatApi.getQueryResultsBetween(
        dateRange[0].toISOString(),
        dateRange[1].toISOString()
      );
      setQueryResults(results || []);
    } catch {
      message.error('Failed to load filtered results');
    } finally {
      setLoading(false);
    }
  };

  // Overall Chart: query count distribution
  const overallChartOption = {
    title: { text: 'Overall Chart', left: 'center' },
    tooltip: { trigger: 'item' as const },
    series: [
      {
        type: 'pie',
        radius: '60%',
        data: [
          { value: queryResults.length, name: 'Total Queries' },
          { value: queryResults.filter((r) => r.resultLimit > 0).length, name: 'With Results' },
        ],
      },
    ],
  };

  // Time Chart: queries over time
  const timeLabels = queryResults.map((r) =>
    new Date(r.createTime).toLocaleDateString()
  );
  const uniqueDates = [...new Set(timeLabels)];
  const queryCounts = uniqueDates.map(
    (date) => timeLabels.filter((l) => l === date).length
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

  // Cost Chart: result sizes
  const costChartOption = {
    title: { text: 'Cost Chart', left: 'center' },
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: queryResults.map((_, i) => `Query ${i + 1}`),
    },
    yAxis: { type: 'value' as const, name: 'Result Limit' },
    series: [
      {
        type: 'bar',
        data: queryResults.map((r) => r.resultLimit),
        itemStyle: { color: '#1890ff' },
      },
    ],
  };

  return (
    <div className="reports-layout">
      <div className="reports-filter">
        <RangePicker
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setDateRange([dates[0], dates[1]]);
            } else {
              setDateRange(null);
            }
          }}
        />
        <Button type="primary" onClick={loadFilteredResults} loading={loading}>
          Filter
        </Button>
        <Button onClick={loadAllResults} loading={loading}>
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
        <Card title="Query Details">
          <div className="query-info-list">
            {queryResults.map((result, index) => (
              <div key={result.id || index} className="query-info-item">
                <span className="query-info-label">Query {index + 1}</span>
                <span className="query-info-time">
                  {new Date(result.createTime).toLocaleString()}
                </span>
                <span className="query-info-limit">
                  Limit: {result.resultLimit}
                </span>
              </div>
            ))}
            {queryResults.length === 0 && (
              <div className="no-data">No query results available</div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};

export default Reports;
