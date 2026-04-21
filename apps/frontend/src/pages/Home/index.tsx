import React, { Suspense, useEffect, useState } from 'react';
import { message, Spin } from 'antd';
import { useSearchParams } from 'react-router-dom';
import Sidebar from '../../components/Sidebar';
import AppHeader from '../../components/Header';
import { useAnalysisStore } from '../../stores/analysisStore';
import { useConversationStore } from '../../stores/conversationStore';
import { useSchemaStore } from '../../stores/schemaStore';
import './index.css';

const Analysis = React.lazy(() => import('../Analysis'));
const Reports = React.lazy(() => import('../Reports'));

const Home: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [collapsed, setCollapsed] = useState(false);
  const [activeView, setActiveView] = useState<string>('analysis');
  const currentThreadId = searchParams.get('threadId');
  const {
    threads,
    currentThread,
    isCreating,
    loadThreads,
    loadConversation,
    createThread,
    clearCurrent,
  } = useConversationStore();
  const { prepareThread, restoreSession } = useAnalysisStore();

  useEffect(() => {
    loadThreads().catch(() => {
      // Keep the page usable even if the thread list cannot be fetched.
    });
  }, [loadThreads]);

  useEffect(() => {
    if (!currentThreadId) {
      clearCurrent();
      prepareThread(null);
      return;
    }

    loadConversation(currentThreadId)
      .then((detail) => restoreSession(detail.history[0] || null, detail.thread.threadId))
      .catch(() => {
        clearCurrent();
        prepareThread(null);
        const nextParams = new URLSearchParams(searchParams);
        nextParams.delete('threadId');
        setSearchParams(nextParams, { replace: true });
      });
  }, [clearCurrent, currentThreadId, loadConversation, prepareThread, restoreSession, searchParams, setSearchParams]);

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
      const thread = await createThread({
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
        threads={threads}
        currentThreadId={currentThreadId}
        creatingThread={isCreating}
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
