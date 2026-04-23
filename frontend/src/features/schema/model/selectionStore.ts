/**
 * `features/schema` feature 的**纯客户端 UI 选中态**——当前用户在侧栏点了
 * 哪个 backend / schema。不承载任何跨刷新持久 / 跨 feature 共享契约的数据。
 *
 * **物理位置**：frontend.md §2 / §3 纪律 3 规定 feature 专属的 zustand 选
 * 中态必须落在 `features/<name>/model/` 下（§3 纪律 1 允许 model/ 内使用
 * zustand 但禁止 import React）。本文件从历史位置 `src/stores/schemaStore.ts`
 * 迁出——那个位置属于"结构未迁完"的过渡层，迁出后 `src/stores/` 目录整
 * 体移除，避免新代码误把通用 store 堆回那里。
 *
 * **不承担的职责**（刻意写出来，防止回潮）：
 *
 * - 不持久化 backend / schema 列表本身——那些走 TanStack Query（见
 *   `features/schema/hooks/useSchemaQueries.ts`）；这里只保留"用户当前选中
 *   哪一个 id / name"的瞬时 UI 选中；
 * - 不"自动选中 backends[0] / schemas[0]"——该副作用属于消费组件（Sidebar
 *   shell）的 `useEffect` 兜底，不能回流到 store，否则会把 "TanStack 到位"
 *   与 "store 赋值" 耦合起来，等同于把服务端快照变相搬回 store；
 * - 不跨 feature 暴露——本文件只通过 `features/schema` 的 barrel
 *   `index.ts` 对外导出 `useSchemaStore`，任何 `@/features/schema/model/*`
 *   的穿透 import 会被 lint-0 捕获（frontend.md §3 "group"）。
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
