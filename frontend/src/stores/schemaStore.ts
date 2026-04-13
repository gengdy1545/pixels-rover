import { create } from 'zustand';

interface SchemaState {
  schemas: string[];
  selectedSchema: string | null;
  tables: Record<string, string[]>;
  setSchemas: (schemas: string[]) => void;
  setSelectedSchema: (schema: string) => void;
  setTables: (schema: string, tables: string[]) => void;
}

export const useSchemaStore = create<SchemaState>((set) => ({
  schemas: [],
  selectedSchema: null,
  tables: {},

  setSchemas: (schemas: string[]) => set({ schemas }),

  setSelectedSchema: (schema: string) => set({ selectedSchema: schema }),

  setTables: (schema: string, tables: string[]) =>
    set((state) => ({
      tables: { ...state.tables, [schema]: tables },
    })),
}));
