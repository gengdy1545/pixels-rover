import React, { useEffect, useState } from 'react';
import { Tree, Menu, Select } from 'antd';
import {
  DatabaseOutlined,
  BarChartOutlined,
  RocketOutlined,
  TableOutlined,
} from '@ant-design/icons';
import { useSchemaStore } from '../../stores/schemaStore';
import type { DataNode } from 'antd/es/tree';
import './index.css';

interface SidebarProps {
  onMenuSelect: (key: string) => void;
  collapsed: boolean;
}

const Sidebar: React.FC<SidebarProps> = ({ onMenuSelect, collapsed }) => {
  const {
    backends,
    selectedBackend,
    schemas,
    selectedSchema,
    tables,
    loadBackends,
    selectBackend,
    setSelectedSchema,
    loadTables,
  } = useSchemaStore();

  const [treeData, setTreeData] = useState<DataNode[]>([]);
  const [activeMenu, setActiveMenu] = useState('analysis');

  useEffect(() => {
    loadBackends();
  }, []);

  useEffect(() => {
    if (selectedSchema) {
      loadTables(selectedSchema);
    }
  }, [selectedSchema]);

  useEffect(() => {
    const nodes: DataNode[] = schemas.map((schema) => ({
      title: schema,
      key: schema,
      icon: <DatabaseOutlined />,
      children: (tables[schema] || []).map((table) => ({
        title: table.name || String(table),
        key: `${schema}.${typeof table === 'string' ? table : table.name}`,
        icon: <TableOutlined />,
        isLeaf: true,
      })),
    }));
    setTreeData(nodes);
  }, [schemas, tables]);

  const onLoadData = async (node: DataNode) => {
    const schemaName = node.key as string;
    if (tables[schemaName]) return;
    await loadTables(schemaName);
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

        {!collapsed && activeMenu === 'schemas' && (
          <div className="schema-tree">
            {backends.length > 1 && (
              <Select
                value={selectedBackend}
                onChange={selectBackend}
                style={{ width: '100%', marginBottom: 8 }}
                size="small"
                options={backends.map((b) => ({
                  value: b.backend_id,
                  label: `${b.backend_id} (${b.backend_type})`,
                }))}
              />
            )}
            <Tree
              treeData={treeData}
              loadData={onLoadData}
              onSelect={handleSchemaSelect}
              showLine
            />
          </div>
        )}
      </nav>
    </aside>
  );
};

export default Sidebar;
