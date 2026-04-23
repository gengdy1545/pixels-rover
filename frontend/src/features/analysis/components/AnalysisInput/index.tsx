import React, { useState } from 'react';
import { Input, Button, Tag, Space } from 'antd';
import { SearchOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { SemanticMetric } from '../../../../shared/types/analysis';
import './index.css';

interface AnalysisInputProps {
  onSubmit: (question: string) => void;
  loading: boolean;
  availableMetrics: SemanticMetric[];
  disabled?: boolean;
}

const AnalysisInput: React.FC<AnalysisInputProps> = ({ onSubmit, loading, availableMetrics, disabled = false }) => {
  const [question, setQuestion] = useState('');

  const handleSubmit = () => {
    const trimmed = question.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  const handleQuickQuestion = (q: string) => {
    setQuestion(q);
  };

  const quickQuestions = [
    '本月北美 GMV 是多少',
    '各区域本月 vs 上月 GMV 对比',
    '本月 GMV 下降的主要原因是什么',
  ];

  return (
    <div className="analysis-input-wrapper">
      <div className="analysis-input-main">
        <Input.TextArea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="请输入您的分析问题，例如：本月北美 GMV 是多少？"
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={loading || disabled}
          className="analysis-textarea"
        />
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          onClick={handleSubmit}
          loading={loading}
          disabled={disabled}
          size="large"
          className="analysis-submit-btn"
        >
          分析
        </Button>
      </div>

      <div className="analysis-input-hints">
        {availableMetrics.length > 0 && (
          <div className="metrics-hint">
            <span className="hint-label">可用指标：</span>
            <Space size={[4, 4]} wrap>
              {availableMetrics.map((m) => (
                <Tag key={m.name} color="blue">
                  {m.display_name || m.name}
                </Tag>
              ))}
            </Space>
          </div>
        )}

        <div className="quick-questions">
          <span className="hint-label">快速提问：</span>
          <Space size={[4, 4]} wrap>
            {quickQuestions.map((q) => (
              <Tag
                key={q}
                className="quick-tag"
                icon={<SearchOutlined />}
                onClick={() => handleQuickQuestion(q)}
                style={{ cursor: 'pointer' }}
              >
                {q}
              </Tag>
            ))}
          </Space>
        </div>
      </div>
    </div>
  );
};

export default AnalysisInput;
