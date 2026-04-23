/**
 * Sidebar——左侧布局 shell。
 *
 * **物理位置**：`app/components/Sidebar/`。
 *
 * 历史位置是 `src/components/Sidebar/`——那个顶层 `components/` 目录属于"结构
 * 未迁完"的过渡层，只剩 Sidebar 一个消费者时随本次上升一并清空删除。Sidebar
 * 是典型的**跨 feature 应用 shell**：同时承载 schema / conversation / reports
 * 三个域的入口，本身不归属任一 feature；按 frontend.md §1 目录形态它属于
 * `app/` 层（应用壳一侧，和 `app/layouts/` / `app/providers/` / `app/router/`
 * 是兄弟）。把它放进任何 `features/<name>/` 都会破坏 §2 纪律 3（feature 只经
 * 由 barrel 相互引用）的单向性：Sidebar 横向依赖三个 feature 的 barrel 是合
 * 法的，但它自身不能被认作任何一个的子组件。
 *
 * **本文件承担的三件事**（Stage 3 §10 PR-3 拆分后不变）：
 *
 *   1. 暗色面板 + logo + 顶层菜单（智能分析 / Schemas / Reports）；
 *   2. 折叠态视觉切换；
 *   3. 根据 `activeMenu` 在菜单下方挂载相应 feature 的子面板
 *      （`SchemaBrowser` / `ConversationList`）——两者分别由各自 feature 的
 *      barrel `@/features/<name>` 导出，Sidebar 不穿透 feature 内部路径。
 *
 * schema 树和对话列表已经分别下沉到：
 *   - `features/schema/components/SchemaBrowser`
 *   - `features/conversation/components/ConversationList`
 */

import React, { useState } from 'react';
import { Menu } from 'antd';
import {
  DatabaseOutlined,
  BarChartOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import { SchemaBrowser } from '../../../features/schema';
import { ConversationList } from '../../../features/conversation';
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
