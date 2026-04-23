/**
 * AppHeader——全站顶栏，承担两件事：
 *
 *   1. 展示当前登录用户（avatar + name）并暴露登出入口；
 *   2. 侧栏折叠按钮（collapsed / onToggleCollapse 由页面布局注入）。
 *
 * 为什么归 features/auth：组件的核心职责就是\"读登录态 + 触发登出\"；
 * 折叠按钮只是为了复用这一条顶栏条带而顺带承载的 layout prop，并不改
 * 变 feature 归属。Home 页通过 `features/auth` barrel 消费本组件——跨
 * feature 访问只经由 barrel（frontend.md §2 纪律 3）。
 */

import React, { useEffect } from 'react';
import { Dropdown, Avatar, Space } from 'antd';
import { UserOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { useAuthStore } from '../../model/store';
import type { MenuProps } from 'antd';
import './index.css';

interface HeaderProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

const AppHeader: React.FC<HeaderProps> = ({ collapsed, onToggleCollapse }) => {
  const { user, checkAuth, logout } = useAuthStore();

  useEffect(() => {
    if (!user) {
      checkAuth();
    }
  }, [user, checkAuth]);

  const handleLogout = async () => {
    await logout();
  };

  const menuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: 'Personal Profile',
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: 'Sign Out',
      onClick: handleLogout,
    },
  ];

  return (
    <header className="app-header">
      <div className="header-left">
        <span className="toggle-btn" onClick={onToggleCollapse}>
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </span>
      </div>
      <div className="header-right">
        <Dropdown menu={{ items: menuItems }} placement="bottomRight">
          <Space className="user-info" style={{ cursor: 'pointer' }}>
            <Avatar src="/images/users/avatar-cat.jpg" size={36} />
            <span className="user-name">{user?.name || 'User'}</span>
          </Space>
        </Dropdown>
      </div>
    </header>
  );
};

export default AppHeader;
