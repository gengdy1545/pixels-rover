import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { message, Spin } from 'antd';
import { useSearchParams } from 'react-router-dom';
import Sidebar from '../../app/components/Sidebar';
import { AppHeader } from '../../features/auth';
import { Reports } from '../../features/report';
import { Analysis, useAnalysisStore } from '../../features/analysis';
import {
  useThreadsQuery,
  useConversationQuery,
  useCreateConversationMutation,
  classifyThreadError,
} from '../../features/conversation';
import { useSchemaStore } from '../../features/schema';
import './index.css';

const Home: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [collapsed, setCollapsed] = useState(false);
  const [activeView, setActiveView] = useState<string>('analysis');
  const currentThreadId = searchParams.get('threadId');

  // 服务端快照全部走 TanStack Query（Stage 2 §12 拆分）：
  //   - threads 列表 → useThreadsQuery
  //   - 某 thread 的详情 → useConversationQuery(currentThreadId)
  // 之前 conversationStore 里还会顺手缓存"currentThread 对象"用于
  // Analysis 头部展示；这里改为从 threads 列表 find——TanStack 已经
  // 保证 list 与 detail 的缓存一致性，不需要额外中间 state。
  const { data: threads = [] } = useThreadsQuery();
  const { data: conversationDetail, error: conversationError } =
    useConversationQuery(currentThreadId);

  const createConversationMutation = useCreateConversationMutation();
  const { prepareThread, restoreSession } = useAnalysisStore();

  const currentThread = useMemo(
    () =>
      conversationDetail?.thread ??
      threads.find((t) => t.threadId === currentThreadId) ??
      null,
    [conversationDetail, threads, currentThreadId],
  );

  useEffect(() => {
    if (!currentThreadId) {
      prepareThread(null);
      return;
    }
    if (conversationDetail) {
      restoreSession(
        conversationDetail.history[0] || null,
        conversationDetail.thread.threadId,
      );
    }
  }, [currentThreadId, conversationDetail, prepareThread, restoreSession]);

  useEffect(() => {
    if (!currentThreadId) return;
    const decision = classifyThreadError(conversationError);
    if (!decision) return;

    // Per-kind UX. Surfacing the specific backend errorCode instead of
    // silently dropping the selection is the backend.md §6.3.2 step-1
    // payoff — "this conversation is archived" vs "we couldn't reach the
    // server" vs "it's gone forever" are different user recoveries.
    if (decision.kind === 'archived') {
      message.warning(decision.message);
    } else if (decision.kind === 'transient') {
      message.error(decision.message);
    } else {
      message.error(decision.message);
    }

    if (decision.stripThreadIdFromUrl) {
      prepareThread(null);
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete('threadId');
      setSearchParams(nextParams, { replace: true });
    }
  }, [currentThreadId, conversationError, prepareThread, searchParams, setSearchParams]);

  const handleMenuSelect = (key: string) => {
    if (key === 'schemas' || key === 'analysis') {
      setActiveView('analysis');
    } else if (key === 'reports') {
      setActiveView('reports');
    }
  };

  const handleThreadSelect = (threadId: string) => {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('threadId', threadId);
    setSearchParams(nextParams);
    setActiveView('analysis');
  };

  const handleCreateThread = async () => {
    const { selectedBackend, selectedSchema } = useSchemaStore.getState();
    if (!selectedBackend) {
      message.warning('Please select a backend first');
      return;
    }

    try {
      const thread = await createConversationMutation.mutateAsync({
        backendId: selectedBackend,
        schemaName: selectedSchema || undefined,
        title: selectedSchema ? `${selectedSchema} 对话` : undefined,
      });
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('threadId', thread.threadId);
      setSearchParams(nextParams);
      prepareThread(thread.threadId);
      setActiveView('analysis');
    } catch (error: unknown) {
      const err = error as Error;
      message.error(err.message || 'Failed to create conversation');
    }
  };

  const renderContent = () => {
    switch (activeView) {
      case 'reports':
        return <Reports />;
      case 'analysis':
      default:
        return <Analysis currentThread={currentThread} onCreateConversation={handleCreateThread} />;
    }
  };

  return (
    <div className="home-layout">
      <Sidebar
        onMenuSelect={handleMenuSelect}
        onThreadSelect={handleThreadSelect}
        onCreateThread={handleCreateThread}
        collapsed={collapsed}
        currentThreadId={currentThreadId}
        creatingThread={createConversationMutation.isPending}
      />
      <div className="home-main">
        <AppHeader collapsed={collapsed} onToggleCollapse={() => setCollapsed(!collapsed)} />
        <main className="home-content">
          <Suspense fallback={<div className="content-loading"><Spin size="large" /></div>}>
            {renderContent()}
          </Suspense>
        </main>
      </div>
    </div>
  );
};

export default Home;
