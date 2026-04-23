/**
 * schema feature 的**纯客户端 UI state**——当前选中的 backend / schema。
 *
 * 收紧历史（Stage 2 `.notes/todolist.md §12`）：原先这个 store 既装了选
 * 中态也装了 `backends` / `schemas` / `tables` / `columns` 四组服务端快
 * 照；这些快照已经全数迁到 TanStack Query（`features/schema/` 下的 hooks
 * + query-key 工厂）。这里只剩"用户当前在 UI 上点了哪个 backend / schema"
 * 这种**不跨刷新持久、不共享上游契约**的前端瞬时状态，继续 zustand。
 *
 * 刻意不把"首次加载后自动选中 `backends[0]` / `schemas[0]`"这条副作用
 * 搬进来——它曾经跟服务端请求耦合在同一个 action 里。现在 backends /
 * schemas 走 `useBackendsQuery` / `useSchemasQuery`，副作用的正确承载点
 * 是消费组件的 `useEffect`（`Sidebar` 里兜底），而不是这一层 store。
 * store 层如果继续塞副作用，就会把 "TanStack 的数据到位" 和 "store 的
 * 选中态被赋值" 重新耦合起来，等同于把快照状态变相搬回来。
 */

import { create } from 'zustand';

interface SchemaUIState {
  selectedBackend: string | null;
  selectedSchema: string | null;
  setSelectedBackend: (backendId: string | null) => void;
  setSelectedSchema: (schemaName: string | null) => void;
}

export const useSchemaStore = create<SchemaUIState>((set) => ({
  selectedBackend: null,
  selectedSchema: null,
  setSelectedBackend: (backendId) =>
    set({ selectedBackend: backendId, selectedSchema: null }),
  setSelectedSchema: (schemaName) => set({ selectedSchema: schemaName }),
}));
