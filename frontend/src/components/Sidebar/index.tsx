import React, { useEffect, useMemo, useState } from 'react';
import { Button, Tree, Menu, Select } from 'antd';
import {
  DatabaseOutlined,
  BarChartOutlined,
  MessageOutlined,
  PlusOutlined,
  RocketOutlined,
  TableOutlined,
} from '@ant-design/icons';
import { useSchemaStore } from '../../stores/schemaStore';
import {
  useBackendsQuery,
  useSchemasQuery,
  useTablesQuery,
} from '../../features/schema';
import type { DataNode } from 'antd/es/tree';
import type { ConversationThread } from '../../shared/types/conversation';
import './index.css';

interface SidebarProps {
  onMenuSelect: (key: string) => void;
  onThreadSelect: (threadId: string) => void;
  onCreateThread: () => void;
  collapsed: boolean;
  threads: ConversationThread[];
  currentThreadId: string | null;
  creatingThread: boolean;
}

const Sidebar: React.FC<SidebarProps> = ({
  onMenuSelect,
  onThreadSelect,
  onCreateThread,
  collapsed,
  threads,
  currentThreadId,
  creatingThread,
}) => {
  const selectedBackend = useSchemaStore((s) => s.selectedBackend);
  const selectedSchema = useSchemaStore((s) => s.selectedSchema);
  const setSelectedBackend = useSchemaStore((s) => s.setSelectedBackend);
  const setSelectedSchema = useSchemaStore((s) => s.setSelectedSchema);

  const { data: backends = [] } = useBackendsQuery();
  const { data: schemas = [] } = useSchemasQuery(selectedBackend);
  // `useTablesQuery` is driven by the currently expanded schema in the tree;
  // only one schema is "hot" at a time (the one the user last clicked to
  // expand). `antd.Tree.loadData` still fires for other schemas, but those
  // reads are served directly by cached `useTablesQuery` hits — see the
  // `onLoadData` handler below.
  const { data: currentTables = [] } = useTablesQuery(
    selectedBackend,
    selectedSchema,
  );

  // 把"schema → tables"的维护下放给 TanStack Query；组件本地只保留
  // "当前渲染的 schema → tables 映射"缓存，供 antd.Tree 消费。把这部分
  // 放 React 组件 state 而不是 zustand 是因为它**只服务这一棵树**，不
  // 跨页面共享；若某天 ReportsPage 也要一份，那时再提回 store。
  const [loadedSchemas, setLoadedSchemas] = useState<
    Record<string, { name: string }[]>
  >({});

  useEffect(() => {
    if (selectedSchema && currentTables.length > 0) {
      setLoadedSchemas((prev) =>
        prev[selectedSchema]
          ? prev
          : { ...prev, [selectedSchema]: currentTables },
      );
    }
  }, [selectedSchema, currentTables]);

  useEffect(() => {
    setLoadedSchemas({});
  }, [selectedBackend]);

  useEffect(() => {
    if (backends.length > 0 && !selectedBackend) {
      setSelectedBackend(backends[0].backend_id);
    }
  }, [backends, selectedBackend, setSelectedBackend]);

  useEffect(() => {
    if (schemas.length > 0 && !selectedSchema) {
      setSelectedSchema(schemas[0]);
    }
  }, [schemas, selectedSchema, setSelectedSchema]);

  const [activeMenu, setActiveMenu] = useState('analysis');

  const treeData = useMemo<DataNode[]>(() => {
    return schemas.map((schema) => ({
      title: schema,
      key: schema,
      icon: <DatabaseOutlined />,
      children: (loadedSchemas[schema] || []).map((table) => ({
        title: table.name || String(table),
        key: `${schema}.${typeof table === 'string' ? table : table.name}`,
        icon: <TableOutlined />,
        isLeaf: true,
      })),
    }));
  }, [schemas, loadedSchemas]);

  const onLoadData = async (node: DataNode) => {
    const schemaName = node.key as string;
    if (loadedSchemas[schemaName]) return;
    // Switching the store-selected schema drives useTablesQuery, whose
    // onSuccess merge into loadedSchemas happens in the effect above.
    setSelectedSchema(schemaName);
  };

  const handleMenuClick = (key: string) => {
    setActiveMenu(key);
    onMenuSelect(key);
  };

  const handleSchemaSelect = (
    _selectedKeys: React.Key[],
    info: { node: DataNode },
  ) => {
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
                onChange={setSelectedBackend}
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

        {!collapsed && activeMenu === 'analysis' && (
          <div className="conversation-list">
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={onCreateThread}
              loading={creatingThread}
              block
              className="conversation-create-btn"
            >
              新建对话
            </Button>

            <div className="conversation-items">
              {threads.map((thread) => (
                <button
                  key={thread.threadId}
                  type="button"
                  className={`conversation-item ${currentThreadId === thread.threadId ? 'is-active' : ''}`}
                  onClick={() => onThreadSelect(thread.threadId)}
                >
                  <MessageOutlined />
                  <span className="conversation-title">{thread.title}</span>
                </button>
              ))}
              {threads.length === 0 && (
                <div className="conversation-empty">还没有对话线程</div>
              )}
            </div>
          </div>
        )}
      </nav>
    </aside>
  );
};

export default Sidebar;
