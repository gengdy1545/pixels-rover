import { create } from 'zustand';
import { conversationApi } from '../shared/api';
import type {
  ConversationDetail,
  ConversationThread,
  CreateConversationRequest,
  UpdateConversationRequest,
} from '../shared/types/conversation';

interface ConversationState {
  threads: ConversationThread[];
  currentThread: ConversationThread | null;
  history: ConversationDetail['history'];
  isLoading: boolean;
  isCreating: boolean;
  loadThreads: () => Promise<ConversationThread[]>;
  createThread: (input: CreateConversationRequest) => Promise<ConversationThread>;
  loadConversation: (threadId: string) => Promise<ConversationDetail>;
  updateThread: (threadId: string, input: UpdateConversationRequest) => Promise<ConversationThread>;
  clearCurrent: () => void;
}

export const useConversationStore = create<ConversationState>((set) => ({
  threads: [],
  currentThread: null,
  history: [],
  isLoading: false,
  isCreating: false,

  loadThreads: async () => {
    set({ isLoading: true });
    try {
      const threads = await conversationApi.listConversations();
      set({ threads, isLoading: false });
      return threads;
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  createThread: async (input) => {
    set({ isCreating: true });
    try {
      const thread = await conversationApi.createConversation(input);
      set((state) => ({
        threads: [thread, ...state.threads.filter((item) => item.threadId !== thread.threadId)],
        currentThread: thread,
        history: [],
        isCreating: false,
      }));
      return thread;
    } catch (error) {
      set({ isCreating: false });
      throw error;
    }
  },

  loadConversation: async (threadId) => {
    set({ isLoading: true });
    try {
      const detail = await conversationApi.getConversation(threadId);
      set((state) => ({
        threads: [
          detail.thread,
          ...state.threads.filter((item) => item.threadId !== detail.thread.threadId),
        ],
        currentThread: detail.thread,
        history: detail.history,
        isLoading: false,
      }));
      return detail;
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  updateThread: async (threadId, input) => {
    const thread = await conversationApi.updateConversation(threadId, input);
    set((state) => ({
      threads: state.threads.map((item) => (item.threadId === threadId ? thread : item)),
      currentThread: state.currentThread?.threadId === threadId ? thread : state.currentThread,
    }));
    return thread;
  },

  clearCurrent: () => {
    set({ currentThread: null, history: [] });
  },
}));
