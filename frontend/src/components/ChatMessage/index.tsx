import React from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { sql } from '@codemirror/lang-sql';
import { Button, Tooltip } from 'antd';
import { PlayCircleOutlined, EditOutlined } from '@ant-design/icons';
import './index.css';

interface ChatMessageProps {
  type: 'user' | 'system' | 'ai';
  content: string;
  sqlText?: string;
  sqlUuid?: string;
  isExecuted?: boolean;
  onExecuteSql?: (sqlText: string, uuid: string) => void;
  onEditSql?: (uuid: string, currentSql: string) => void;
}

const ChatMessage: React.FC<ChatMessageProps> = ({
  type,
  content,
  sqlText,
  sqlUuid,
  isExecuted,
  onExecuteSql,
  onEditSql,
}) => {
  return (
    <div className={`chat-message chat-message-${type}`}>
      {type === 'system' && (
        <img className="avatar-image" src="/images/logo-ico.png" alt="system" />
      )}
      <div className="message-content">
        <div className="message-text">{content}</div>
        {sqlText && (
          <div className="sql-block">
            <CodeMirror
              value={sqlText}
              extensions={[sql()]}
              editable={false}
              basicSetup={{ lineNumbers: true, foldGutter: false }}
              height="auto"
              minHeight="40px"
              maxHeight="200px"
            />
            <div className="sql-actions">
              {onEditSql && sqlUuid && (
                <Tooltip title="Edit SQL">
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => onEditSql(sqlUuid, sqlText)}
                  />
                </Tooltip>
              )}
              {onExecuteSql && sqlUuid && (
                <Tooltip title="Execute SQL">
                  <Button
                    type="text"
                    size="small"
                    icon={<PlayCircleOutlined />}
                    onClick={() => onExecuteSql(sqlText, sqlUuid)}
                    style={{ color: isExecuted ? '#52c41a' : '#1890ff' }}
                  />
                </Tooltip>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatMessage;
