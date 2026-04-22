import { get, patch, post } from '../client';
import type {
  ConversationDetail,
  ConversationThread,
  CreateConversationRequest,
  UpdateConversationRequest,
} from '../../types/conversation';

export const conversationApi = {
  createConversation: (data: CreateConversationRequest) =>
    post<ConversationThread>('/api/v1/conversations', data),

  listConversations: () =>
    get<ConversationThread[]>('/api/v1/conversations'),

  getConversation: (threadId: string) =>
    get<ConversationDetail>(`/api/v1/conversations/${threadId}`),

  updateConversation: (threadId: string, data: UpdateConversationRequest) =>
    patch<ConversationThread>(`/api/v1/conversations/${threadId}`, data),
};

