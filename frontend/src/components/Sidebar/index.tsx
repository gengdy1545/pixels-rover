import React, { useEffect, useState } from 'react';
import { Tree, Menu } from 'antd';
import { DatabaseOutlined, BarChartOutlined, SettingOutlined } from '@ant-design/icons';
import { metadataApi } from '../../services/metadataApi';
import { useSchemaStore } from '../../stores/schemaStore';
import type { DataNode } from 'antd/es/tree';
import './index.css';

interface SidebarProps {
  onMenuSelect: (key: string) => void;
  collapsed: boolean;
}

const Sidebar: React.FC<SidebarProps> = ({ onMenuSelect, collapsed }) => {
  const { schemas, setSchemas, setTables, tables, setSelectedSchema } = useSchemaStore();
  const [treeData, setTreeData] = useState<DataNode[]>([]);
  const [activeMenu, setActiveMenu] = useState('translator');

  useEffect(() => {
    loadSchemas();
  }, []);

  useEffect(() => {
    const nodes: DataNode[] = schemas.map((schema) => ({
      title: schema,
      key: schema,
      children: (tables[schema] || []).map((table) => ({
        title: table,
        key: `${schema}.${table}`,
        isLeaf: true,
      })),
    }));
    setTreeData(nodes);
  }, [schemas, tables]);

  const loadSchemas = async () => {
    try {
      const response = await metadataApi.getSchemas();
      const data = response.data.data as { schemaNames?: string[] };
      const schemaNames = data?.schemaNames || [];
      setSchemas(schemaNames);
    } catch {
      // Silently fail
    }
  };

  const onLoadData = async (node: DataNode) => {
    const schemaName = node.key as string;
    if (tables[schemaName]) return;
    try {
      const response = await metadataApi.getTables(schemaName);
      const data = response.data.data as { tableNames?: string[] };
      const tableNames = data?.tableNames || [];
      setTables(schemaName, tableNames);
    } catch {
      // Silently fail
    }
  };

  const handleMenuClick = (key: string) => {
    setActiveMenu(key);
    onMenuSelect(key);
  };

  const handleSchemaSelect = (_selectedKeys: React.Key[], info: { node: DataNode }) => {
    const key = info.node.key as string;
    if (!key.includes('.')) {
      setSelectedSchema(key);
    }
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
              key: 'schemas',
              icon: <DatabaseOutlined />,
              label: 'Schemas',
              children: [],
            },
            {
              key: 'reports',
              icon: <BarChartOutlined />,
              label: 'Reports',
            },
            {
              key: 'settings',
              icon: <SettingOutlined />,
              label: 'Settings',
            },
          ]}
          onClick={({ key }) => handleMenuClick(key)}
        />

        <div className="schema-tree">
          <Tree
            treeData={treeData}
            loadData={onLoadData}
            onSelect={handleSchemaSelect}
            showLine
          />
        </div>
      </nav>
    </aside>
  );
};

export default Sidebar;
