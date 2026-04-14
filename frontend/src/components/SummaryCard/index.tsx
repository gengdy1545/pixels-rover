import React from 'react';
import { Card, Alert, Typography } from 'antd';
import { BulbOutlined, WarningOutlined } from '@ant-design/icons';

const { Paragraph } = Typography;

interface SummaryCardProps {
  summary: string | null;
  warnings: string[];
  error?: string | null;
  status: string;
}

const SummaryCard: React.FC<SummaryCardProps> = ({ summary, warnings, error, status }) => {
  return (
    <div>
      {error && status === 'failed' && (
        <Alert
          type="error"
          message="分析失败"
          description={error}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {error && status === 'clarification_needed' && (
        <Alert
          type="info"
          message="需要更多信息"
          description={error}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {warnings.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {warnings.map((w, i) => (
            <Alert
              key={i}
              type="warning"
              message={w}
              icon={<WarningOutlined />}
              showIcon
              banner
              style={{ marginBottom: 4 }}
            />
          ))}
        </div>
      )}

      {summary && (
        <Card
          size="small"
          title={
            <span>
              <BulbOutlined style={{ color: '#faad14', marginRight: 8 }} />
              分析结论
            </span>
          }
          style={{
            borderColor: '#ffe58f',
            background: 'linear-gradient(135deg, #fffbe6 0%, #fff 100%)',
          }}
        >
          <Paragraph style={{ fontSize: 15, margin: 0, lineHeight: 1.8 }}>
            {summary}
          </Paragraph>
        </Card>
      )}
    </div>
  );
};

export default SummaryCard;
