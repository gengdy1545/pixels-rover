/**
 * Sidebar——左侧布局 shell。
 *
 * Stage 3 §10 PR-3 拆分后，本文件**只承担三件事**：
 *
 *   1. 暗色面板 + logo + 顶层菜单（智能分析 / Schemas / Reports）；
 *   2. 折叠态视觉切换；
 *   3. 根据 `activeMenu` 在菜单下方挂载相应 feature 的子面板。
 *
 * schema 树和对话列表已经分别下沉到：
 *   - `features/schema/components/SchemaBrowser`
 *   - `features/conversation/components/ConversationList`
 *
 * 跨 feature 访问只经由各自的 barrel（`@/features/<name>`），符合
 * frontend.md §2 纪律 3。
 *
 * 为什么 Sidebar 留在 `components/` 而不搬进任何 feature：它是
 * **跨 feature 的应用 shell**——同时承载 schema / conversation / reports
 * 三个域的入口；按 §1.1.1 / §2 应该归 `app/components/` 这一层，但 Stage
 * 3 §10 没把这步包进 PR-3 的 scope（PR-3 只关心 conversation/schema 自
 * 有 UI 进 feature）。后续 app shell 重构 PR 再把 Sidebar 上升到
 * `app/components/Sidebar/`，现阶段保持原位。
 */

import React, { useState } from 'react';
import { Menu } from 'antd';
import {
  DatabaseOutlined,
  BarChartOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import { SchemaBrowser } from '../../features/schema';
import { ConversationList } from '../../features/conversation';
import './index.css';

interface SidebarProps {
  onMenuSelect: (key: string) => void;
  onThreadSelect: (threadId: string) => void;
  onCreateThread: () => void;
  collapsed: boolean;
  currentThreadId: string | null;
  creatingThread: boolean;
}

const Sidebar: React.FC<SidebarProps> = ({
  onMenuSelect,
  onThreadSelect,
  onCreateThread,
  collapsed,
  currentThreadId,
  creatingThread,
}) => {
  const [activeMenu, setActiveMenu] = useState('analysis');

  const handleMenuClick = (key: string) => {
    setActiveMenu(key);
    onMenuSelect(key);
  };

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <div className="sidebar-header">
        <a href="/home">
          <img src="/images/logo-sidebar.png" alt="PixelsDB" className="sidebar-logo" />
        </a>
      </div>

      <nav className="sidebar-nav">
        <Menu
          mode="inline"
          selectedKeys={[activeMenu]}
          style={{ borderRight: 0 }}
          items={[
            {
              key: 'analysis',
              icon: <RocketOutlined />,
              label: '智能分析',
            },
            {
              key: 'schemas',
              icon: <DatabaseOutlined />,
              label: 'Schemas',
            },
            {
              key: 'reports',
              icon: <BarChartOutlined />,
              label: 'Reports',
            },
          ]}
          onClick={({ key }) => handleMenuClick(key)}
        />

        {!collapsed && activeMenu === 'schemas' && <SchemaBrowser />}

        {!collapsed && activeMenu === 'analysis' && (
          <ConversationList
            currentThreadId={currentThreadId}
            onThreadSelect={onThreadSelect}
            onCreateThread={onCreateThread}
            creatingThread={creatingThread}
          />
        )}
      </nav>
    </aside>
  );
};

export default Sidebar;
