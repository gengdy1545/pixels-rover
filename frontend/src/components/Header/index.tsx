import React, { useEffect } from 'react';
import { Dropdown, Avatar, Space } from 'antd';
import { UserOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import type { MenuProps } from 'antd';
import './index.css';

interface HeaderProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

const AppHeader: React.FC<HeaderProps> = ({ collapsed, onToggleCollapse }) => {
  const { user, fetchUserInfo, logout } = useAuthStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (!user) {
      fetchUserInfo();
    }
  }, [user, fetchUserInfo]);

  const handleLogout = () => {
    logout();
    navigate('/login');
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
