/**
 * SchemaBrowser——schema feature 的导览面板。
 *
 * 历史上这段 UI 嵌在 `components/Sidebar/index.tsx` 里跟"对话列表"和
 * "全站菜单"挤同一个文件；Stage 3 §10 PR-3 把它单独抽进本 feature 后：
 *
 *   - 数据来源全部走 feature 内部资产：`useSchemaStore` 拿当前选中态、
 *     `useBackendsQuery` / `useSchemasQuery` / `useTablesQuery` 拿三层
 *     元数据。组件**不接受任何 schema 域的 props**；它的整条状态机都
 *     是 feature 内自洽的。
 *   - 副作用编排（"backends 加载完默认选第一个"、"schemas 加载完默认
 *     选第一个"、"切 backend 时清掉懒加载的 tables 缓存"）保留在组件
 *     层 useEffect——按 `frontend.md §1.1.1 / §2 纪律 1`，store 不写副
 *     作用，hooks 也不替组件做"默认选中"的策略选择，所以归宿就是这个
 *     消费组件本身。
 *   - 懒加载缓存 `loadedSchemas` 是**\"当前这棵 antd.Tree 自己的局部展开
 *     视图\"**，只服务这个组件实例，故而留组件 useState；如果未来某天
 *     ReportsPage 也要同一份展开视图，那时再提到 store。
 *
 * Props 仅用 `Pick<HTMLAttributes, 'className'>` 这一类**纯展示包装**
 * 控制。schema 域内的所有概念都不通过 prop 暴露——这就是\"feature
 * 自洽组件\"的判据。
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Tree, Select } from 'antd';
import { DatabaseOutlined, TableOutlined } from '@ant-design/icons';
import type { DataNode } from 'antd/es/tree';
import { useSchemaStore } from '../../../../stores/schemaStore';
import {
  useBackendsQuery,
  useSchemasQuery,
  useTablesQuery,
} from '../../hooks/useSchemaQueries';
import './index.css';

const SchemaBrowser: React.FC = () => {
  const selectedBackend = useSchemaStore((s) => s.selectedBackend);
  const selectedSchema = useSchemaStore((s) => s.selectedSchema);
  const setSelectedBackend = useSchemaStore((s) => s.setSelectedBackend);
  const setSelectedSchema = useSchemaStore((s) => s.setSelectedSchema);

  const { data: backends = [] } = useBackendsQuery();
  const { data: schemas = [] } = useSchemasQuery(selectedBackend);
  // 当前\"被点中展开\"的 schema 由 useSchemaStore.selectedSchema 驱动；
  // 其它 schema 的 tables 命中是 antd.Tree.loadData 下方的事件 →
  // setSelectedSchema → 这条 useTablesQuery 重新跑一轮。多个 schema
  // 的结果靠 `loadedSchemas` 在组件里堆积成完整树。
  const { data: currentTables = [] } = useTablesQuery(
    selectedBackend,
    selectedSchema,
  );

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
    // 切换 store 选中态会重新驱动 useTablesQuery；上面的 useEffect 在新
    // tables 到位后把它合进 loadedSchemas，避免子节点 lazy load 长期空。
    setSelectedSchema(schemaName);
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
  );
};

export default SchemaBrowser;
