import React, { useState, Suspense } from 'react';
import { Spin } from 'antd';
import Sidebar from '../../components/Sidebar';
import AppHeader from '../../components/Header';
import './index.css';

// Lazy load content pages
const Translator = React.lazy(() => import('../Translator'));
const Reports = React.lazy(() => import('../Reports'));

const Home: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [activeView, setActiveView] = useState<string>('translator');

  const handleMenuSelect = (key: string) => {
    if (key === 'schemas' || key === 'translator') {
      setActiveView('translator');
    } else if (key === 'reports') {
      setActiveView('reports');
    }
  };

  const renderContent = () => {
    switch (activeView) {
      case 'reports':
        return <Reports />;
      case 'translator':
      default:
        return <Translator />;
    }
  };

  return (
    <div className="home-layout">
      <Sidebar onMenuSelect={handleMenuSelect} collapsed={collapsed} />
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
