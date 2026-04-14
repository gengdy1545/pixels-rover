import { create } from 'zustand';
import { metadataApi } from '../services/metadataApi';
import type { BackendInfo, TableInfo, ColumnInfo } from '../types/analysis';

interface SchemaState {
  backends: BackendInfo[];
  selectedBackend: string | null;
  schemas: string[];
  selectedSchema: string | null;
  tables: Record<string, TableInfo[]>;
  columns: Record<string, ColumnInfo[]>;

  loadBackends: () => Promise<void>;
  selectBackend: (backendId: string) => Promise<void>;
  setSelectedSchema: (schema: string) => void;
  loadTables: (schema: string) => Promise<void>;
  loadColumns: (schema: string, table: string) => Promise<void>;
}

export const useSchemaStore = create<SchemaState>((set, get) => ({
  backends: [],
  selectedBackend: null,
  schemas: [],
  selectedSchema: null,
  tables: {},
  columns: {},

  loadBackends: async () => {
    try {
      const response = await metadataApi.getBackends();
      const backends = response.data;
      set({ backends });
      if (backends.length > 0 && !get().selectedBackend) {
        await get().selectBackend(backends[0].backend_id);
      }
    } catch {
      // silently fail
    }
  },

  selectBackend: async (backendId: string) => {
    set({ selectedBackend: backendId, schemas: [], selectedSchema: null, tables: {} });
    try {
      const response = await metadataApi.getSchemas(backendId);
      const schemas = response.data.schemas || [];
      set({ schemas });
      if (schemas.length > 0) {
        set({ selectedSchema: schemas[0] });
      }
    } catch {
      // silently fail
    }
  },

  setSelectedSchema: (schema: string) => {
    set({ selectedSchema: schema });
  },

  loadTables: async (schema: string) => {
    const backendId = get().selectedBackend;
    if (!backendId) return;
    if (get().tables[schema]) return;
    try {
      const response = await metadataApi.getTables(backendId, schema);
      const tables = response.data.tables || [];
      set((state) => ({
        tables: { ...state.tables, [schema]: tables },
      }));
    } catch {
      // silently fail
    }
  },

  loadColumns: async (schema: string, table: string) => {
    const backendId = get().selectedBackend;
    if (!backendId) return;
    const key = `${schema}.${table}`;
    if (get().columns[key]) return;
    try {
      const response = await metadataApi.getColumns(backendId, schema, table);
      const columns = response.data.columns || [];
      set((state) => ({
        columns: { ...state.columns, [key]: columns },
      }));
    } catch {
      // silently fail
    }
  },
}));
