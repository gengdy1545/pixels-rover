import React, { useState, useEffect, useRef } from 'react';
import { Input, Button, Select, Modal, InputNumber, message, Table } from 'antd';
import { SendOutlined, FullscreenOutlined, FullscreenExitOutlined } from '@ant-design/icons';
import ChatMessage from '../../components/ChatMessage';
import { chatApi, queryApi } from '../../api';
import { useSchemaStore } from '../../stores/schemaStore';
import './index.css';

interface ChatMsg {
  id: string;
  type: 'user' | 'system' | 'ai';
  content: string;
  sqlText?: string;
  sqlUuid?: string;
  isExecuted?: boolean;
}

interface QueryResultData {
  columns: string[];
  rows: Record<string, unknown>[];
}

const Translator: React.FC = () => {
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: 'welcome',
      type: 'system',
      content: 'Welcome to PixelsDB!\nYou can send question and translate it to SQL query.',
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<QueryResultData | null>(null);
  const [leftFullscreen, setLeftFullscreen] = useState(false);
  const [rightFullscreen, setRightFullscreen] = useState(false);
  const [executeModalVisible, setExecuteModalVisible] = useState(false);
  const [pendingSql, setPendingSql] = useState('');
  const [pendingSqlUuid, setPendingSqlUuid] = useState('');
  const [outputLimit, setOutputLimit] = useState<number>(100);
  const chatAreaRef = useRef<HTMLDivElement>(null);

  const { schemas, selectedSchema, setSelectedSchema } = useSchemaStore();

  useEffect(() => {
    loadChatHistory();
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const scrollToBottom = () => {
    if (chatAreaRef.current) {
      chatAreaRef.current.scrollTop = chatAreaRef.current.scrollHeight;
    }
  };

  const loadChatHistory = async () => {
    try {
      const history = await chatApi.getChatHistory();
      if (history && history.length > 0) {
        const historyMessages: ChatMsg[] = [];
        history.forEach((item) => {
          historyMessages.push({
            id: item.userMessageUuid,
            type: 'user',
            content: item.userMessage,
          });
          historyMessages.push({
            id: item.sqlStatementsUuid,
            type: 'ai',
            content: 'Generated SQL:',
            sqlText: item.sqlText,
            sqlUuid: item.sqlStatementsUuid,
            isExecuted: item.isExecuted,
          });
        });
        setMessages((prev) => [...prev, ...historyMessages]);
      }
    } catch {
      // Silently fail
    }
  };

  const generateUuid = () => {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  };

  const sendMessage = async () => {
    if (!inputValue.trim()) return;
    if (!selectedSchema) {
      message.warning('Please select a schema first');
      return;
    }

    const userMsgUuid = generateUuid();
    const userMsg: ChatMsg = {
      id: userMsgUuid,
      type: 'user',
      content: inputValue,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setLoading(true);

    try {
      const data = await chatApi.textToSql({
        question: inputValue,
        schemaName: selectedSchema,
        tables: [],
        columns: {},
      }) as { sql?: string };
      const sqlText = data?.sql || '';
      const sqlUuid = generateUuid();

      // Save message to backend
      await chatApi.saveMessage(sqlUuid, sqlText, inputValue, userMsgUuid);

      const aiMsg: ChatMsg = {
        id: sqlUuid,
        type: 'ai',
        content: 'Generated SQL:',
        sqlText,
        sqlUuid,
        isExecuted: false,
      };
      setMessages((prev) => [...prev, aiMsg]);
    } catch (error: unknown) {
      const err = error as Error;
      message.error(err.message || 'Failed to translate');
    } finally {
      setLoading(false);
    }
  };

  const handleExecuteSql = (sqlText: string, uuid: string) => {
    setPendingSql(sqlText);
    setPendingSqlUuid(uuid);
    setExecuteModalVisible(true);
  };

  const confirmExecuteSql = async () => {
    setExecuteModalVisible(false);
    try {
      const data = await queryApi.submitQuery({
        sql: pendingSql,
        schemaName: selectedSchema || '',
      }) as { queryId?: string };
      if (data?.queryId) {
        // Poll for results
        await pollQueryResult(data.queryId, pendingSqlUuid);
      }
    } catch (error: unknown) {
      const err = error as Error;
      message.error(err.message || 'Query execution failed');
    }
  };

  const pollQueryResult = async (queryId: string, sqlUuid: string) => {
    const maxAttempts = 30;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        const statusData = await queryApi.getQueryStatus(queryId) as { status?: string };
        if (statusData?.status === 'FINISHED') {
          const resultData = await queryApi.getQueryResult(queryId) as { columns?: string[]; rows?: Record<string, unknown>[] };
          if (resultData) {
            setQueryResult({
              columns: resultData.columns || [],
              rows: resultData.rows || [],
            });
            // Save query result
            const resultUuid = generateUuid();
            await chatApi.saveQueryResult(
              sqlUuid,
              JSON.stringify(resultData),
              outputLimit,
              resultUuid
            );
            // Update message as executed
            setMessages((prev) =>
              prev.map((msg) =>
                msg.sqlUuid === sqlUuid ? { ...msg, isExecuted: true } : msg
              )
            );
          }
          return;
        } else if (statusData?.status === 'FAILED') {
          message.error('Query execution failed');
          return;
        }
      } catch {
        // Continue polling
      }
    }
    message.error('Query timed out');
  };

  const handleEditSql = async (uuid: string, currentSql: string) => {
    Modal.confirm({
      title: 'Edit SQL',
      content: (
        <Input.TextArea
          defaultValue={currentSql}
          rows={4}
          id="edit-sql-textarea"
        />
      ),
      onOk: async () => {
        const textarea = document.getElementById('edit-sql-textarea') as HTMLTextAreaElement;
        if (textarea) {
          const newSql = textarea.value;
          await chatApi.updateSql(uuid, newSql);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.sqlUuid === uuid ? { ...msg, sqlText: newSql } : msg
            )
          );
          message.success('SQL updated');
        }
      },
    });
  };

  const resultColumns = queryResult?.columns.map((col) => ({
    title: col,
    dataIndex: col,
    key: col,
    ellipsis: true,
  })) || [];

  return (
    <div className="translator-layout">
      {/* Left: Translator */}
      <div className={`translator-left ${leftFullscreen ? 'fullscreen' : ''}`}>
        <div className="content-title">
          <span className="content-title-name">Translator</span>
          <Button
            type="text"
            icon={leftFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
            onClick={() => setLeftFullscreen(!leftFullscreen)}
          />
        </div>

        <div className="chat-area" ref={chatAreaRef}>
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              type={msg.type}
              content={msg.content}
              sqlText={msg.sqlText}
              sqlUuid={msg.sqlUuid}
              isExecuted={msg.isExecuted}
              onExecuteSql={handleExecuteSql}
              onEditSql={handleEditSql}
            />
          ))}
        </div>

        <div className="send-message-area">
          <Select
            placeholder="Select schema"
            value={selectedSchema}
            onChange={setSelectedSchema}
            style={{ width: 150 }}
            options={schemas.map((s) => ({ label: s, value: s }))}
          />
          <Input
            placeholder="question"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onPressEnter={sendMessage}
            style={{ flex: 1 }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={loading}
            onClick={sendMessage}
          >
            Send
          </Button>
        </div>
      </div>

      {/* Resize handle */}
      <div className="resize-handle" />

      {/* Right: Query Result */}
      <div className={`translator-right ${rightFullscreen ? 'fullscreen' : ''}`}>
        <div className="content-title">
          <span className="content-title-name">Query Result</span>
          <Button
            type="text"
            icon={rightFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
            onClick={() => setRightFullscreen(!rightFullscreen)}
          />
        </div>

        <div className="result-area">
          {queryResult ? (
            <Table
              columns={resultColumns}
              dataSource={queryResult.rows.map((row, idx) => ({ ...row, key: idx }))}
              size="small"
              scroll={{ x: 'max-content', y: 400 }}
              pagination={{ pageSize: 50 }}
            />
          ) : (
            <div className="result-placeholder">
              Execute a query to see results here.
            </div>
          )}
        </div>
      </div>

      {/* Execute Modal */}
      <Modal
        title="Execute Query"
        open={executeModalVisible}
        onOk={confirmExecuteSql}
        onCancel={() => setExecuteModalVisible(false)}
      >
        <p style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{pendingSql}</p>
        <div style={{ marginTop: 10 }}>
          <span>Output rows limit: </span>
          <InputNumber
            min={1}
            max={10000}
            value={outputLimit}
            onChange={(v) => setOutputLimit(v || 100)}
          />
        </div>
      </Modal>
    </div>
  );
};

export default Translator;
