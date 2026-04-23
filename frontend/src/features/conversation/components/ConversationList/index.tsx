/**
 * ConversationList——conversation feature 的对话线程导航。
 *
 * 历史上这段 UI 嵌在 `components/Sidebar/index.tsx` 里跟 SchemaBrowser 共
 * 用一个文件；Stage 3 §10 PR-3 拆出后：
 *
 *   - threads 列表通过 `useThreadsQuery` 自取，不再由 Sidebar 父组件做
 *     prop drill；多个组件并行调 `useThreadsQuery` 由 TanStack Query
 *     的 dedupe 机制保证只触发一次网络请求。
 *   - 仍然以 props 形式接受三件**应用编排级别**的输入：
 *
 *       - `currentThreadId`：从 URL `searchParams` 派生（Home 持有）；
 *         conversation feature 不该重新发明一套\"当前 thread\"的存储。
 *       - `onThreadSelect(threadId)`：触发的不只是\"选中\"，还包括 URL
 *         切换 + 视图切回 analysis；这是 app 层路由 + 视图编排，跟
 *         conversation feature 边界无关。
 *       - `onCreateThread()`：触发 create mutation 之外，还会 navigate
 *         + 切 view + 通知 analysisStore 准备线程；同上属于编排逻辑。
 *
 *     如果把这三件事吸进组件内部，就要让 conversation feature 反向依赖
 *     react-router-dom + analysis store + URL 协议，违反 frontend.md §2
 *     纪律 3 的依赖方向（feature 不应往 app/ 反射）。所以这里坚持\"展
 *     示组件 + 父注入编排\"的边界。
 *
 *   - `creatingThread` 是父组件持有的 mutation `isPending`——本组件不
 *     去 own 这条 mutation 是因为 mutation 的 `onSuccess` 链路（路由
 *     navigate）在父组件里，把 mutation 拆开两边持反而更乱。
 */

import React from 'react';
import { Button } from 'antd';
import { MessageOutlined, PlusOutlined } from '@ant-design/icons';
import { useThreadsQuery } from '../../hooks/useConversationQueries';
import './index.css';

interface ConversationListProps {
  currentThreadId: string | null;
  onThreadSelect: (threadId: string) => void;
  onCreateThread: () => void;
  creatingThread: boolean;
}

const ConversationList: React.FC<ConversationListProps> = ({
  currentThreadId,
  onThreadSelect,
  onCreateThread,
  creatingThread,
}) => {
  const { data: threads = [] } = useThreadsQuery();

  return (
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
  );
};

export default ConversationList;
