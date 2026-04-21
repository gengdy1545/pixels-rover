# 前端开发指南

本文档固定 Pixels Rover **单 Web 前端** 的目录契约与开发纪律。

- 适用范围：仓库中 `frontend/` 目录（即 Web SPA）。
- 设计前提：产品长期只保留一种客户端（网页），**不会**拆 `apps/mobile`、`apps/desktop`，**不会**引入 `packages/*` 共享层或 monorepo 工具链。
- 文档目的：让任何新同学在不读历史对话的情况下，也能按一致的方式加代码；同时让结构本身在未来万一需要多端时可以低成本抽离，而不需要现在付出多端的工程税。
- 该文档与 [`.notes/engineering-design.md`](../../.notes/engineering-design.md)、[`.notes/todolist.md`](../../.notes/todolist.md) 长期保持一致。以代码事实为准，若代码与本文档出现漂移，优先修正代码或及时更新本文档。

---

## 1. 目录结构（唯一正确形态）

```text
frontend/
├── src/
│   ├── app/                    应用壳：路由、layout、全局 provider、薄页面
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── providers/          AntD ConfigProvider、ThemeProvider、QueryClientProvider 等
│   │   ├── router/             路由定义、lazy import
│   │   ├── layouts/            AppLayout、AuthLayout 等
│   │   └── pages/              页面级组件，只做 feature 装配，不含业务逻辑
│   ├── features/               按业务域拆分，每个 feature 自闭
│   │   ├── auth/
│   │   ├── conversation/
│   │   ├── analysis/
│   │   ├── report/
│   │   └── schema/
│   ├── shared/                 跨 feature 通用，但不包含业务含义
│   │   ├── api/                axios client、SSE 客户端、拦截器（纯网络层）
│   │   ├── storage/            cookie、localStorage、request-id 等浏览器副作用
│   │   ├── ui/                 真正跨 feature 的视图原子（见 §4.3）
│   │   ├── lib/                纯函数工具（格式化、日期、数值）
│   │   ├── config/             运行时配置与常量（仅承载 URL 前缀、CSP 常量、轮询周期等
│   │   │                       静态配置值；严禁放入密钥、token、租户信息等可变或敏感值，
│   │   │                       这类值一律由 gateway 注入的 cookie/header 承担）
│   │   └── types/              后端契约类型（API schema 的前端镜像）
│   ├── styles/                 全局样式、CSS 变量、token
│   ├── index.css
│   └── vite-env.d.ts
├── index.html
├── nginx.conf
├── vite.config.ts
├── tsconfig.json
├── package.json
└── Dockerfile
```

### 1.1 每个 feature 的内部固定形态

```text
features/<domain>/
├── components/        React 组件；只能依赖本 feature 的 hooks/services/model
├── hooks/             React hook；调用 services 并绑定 model
├── services/          纯函数 / 类：API 调用封装、SSE 订阅、业务计算
├── model/
│   ├── types.ts       feature 内部业务类型（与后端契约类型区分）
│   ├── store.ts       Zustand slice 或 TanStack Query key 定义
│   └── selectors.ts   对 store 的派生计算
└── index.ts           对外 barrel：只暴露 hooks / 组件 / 类型；不暴露内部文件
```

### 1.2 feature 目录命名规则

- **kebab-case**：例 `features/auth`、`features/report-viewer`、`features/schema-explorer`。
- 单词 feature 直接用小写单词；多词 feature 用 `-` 连接，与路由 URL 风格一致。
- **禁止**：`reportViewer`（camelCase）、`ReportViewer`（PascalCase）、`report_viewer`（snake_case）。
- 路径引用统一写小写 kebab：`@/features/report-viewer`。

---

## 2. 三条必须守住的纪律

下面三条纪律是**整套结构能长期不腐化的全部前提**。不需要额外工具、不需要 monorepo、不需要新文档——只需要把这三条写进 PR 模板和 code review checklist。

### 纪律 1：`features/*/model/` 里**永远不 import React**

**允许：**

- 纯 TypeScript 类型定义
- 纯函数
- Zustand store（`zustand` 自身不依赖 React 渲染层）
- TanStack Query 的 `queryKey` / `queryFn` 定义

**禁止：**

- `useState`、`useEffect`、`useRef` 等 React hooks
- `react-router` hooks（`useNavigate`、`useParams`）
- AntD 组件或任何依赖 React 渲染树的 API
- `document`、`window` 的直接调用（浏览器副作用统一走 `shared/storage/`）

**为什么：**

- 让 `model/` 可以被任何 hook 消费，也可以被脱离渲染环境的纯逻辑单元测试直接覆盖。
- 让 `model/` 成为未来任何跨端场景（RN、Electron、Node 脚本）的**唯一天然复用单元**；即使永远不做多端，这条纪律仍然保证了可测性。

**示例（反例）：**

```ts
// features/analysis/model/store.ts —— 反面教材
import { useEffect } from 'react';             // 禁止
import { useNavigate } from 'react-router-dom'; // 禁止

export const useAnalysisBadStore = () => {
  const nav = useNavigate();                    // 禁止
  useEffect(() => { /* ... */ }, []);           // 禁止
};
```

**示例（正例）：**

```ts
// features/analysis/model/store.ts
import { create } from 'zustand';
import type { AnalysisSession } from './types';

interface AnalysisState {
  current: AnalysisSession | null;
  setCurrent: (s: AnalysisSession | null) => void;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  current: null,
  setCurrent: (s) => set({ current: s }),
}));
```

### 纪律 2：`shared/api/` 只做"网络契约"，浏览器副作用一律放 `shared/storage/`

**`shared/api/` 允许：**

- axios 实例、SSE 客户端、拦截器
- 请求/响应类型解析
- 通用错误归一化

**`shared/api/` 禁止：**

- 读写 `document.cookie`
- 读写 `localStorage` / `sessionStorage`
- 生成或存取 `X-Request-Id` 等跨请求状态
- 任何 `window` / `document` 访问

**所有浏览器副作用必须统一放在 `shared/storage/`：**

- `cookie.ts`：cookie 读写（当前的 CSRF token、logged_in 等）
- `requestId.ts`：生成与缓存请求关联的 id
- `localStorage.ts`：若有持久化 UI 偏好等

**为什么：**

- `shared/api/` 就是项目与后端之间的**纯网络契约**，未来万一真的要在非浏览器环境下调用，只需要替换 `shared/storage/`，不需要动网络层。
- 即使永不换运行时，这种分层也让"模拟 cookie / 模拟 request-id" 的单测配置变成一行注入，而不是全局 monkey patch。

**示例：**

```ts
// shared/api/client.ts
import axios from 'axios';
import { readCsrfToken } from '@/shared/storage/cookie';
import { ensureRequestId } from '@/shared/storage/requestId';

export const apiClient = axios.create({ baseURL: '', withCredentials: true });
// baseURL 必须是 ''（见 §4.6），业务调用写完整路径 '/api/v1/...'

apiClient.interceptors.request.use((config) => {
  const csrf = readCsrfToken();
  if (csrf) config.headers['X-XSRF-TOKEN'] = csrf;
  config.headers['X-Request-Id'] = ensureRequestId();
  return config;
});
```

`shared/api/client.ts` 本身**不碰 `document.cookie`**，只调用 `shared/storage/` 暴露的函数。这就是纪律 2 的落地形态。

### 纪律 3：跨 feature 只通过 `features/<name>/index.ts` 互相引用

**允许：**

```ts
import { useAnalysisSession, type AnalysisSession } from '@/features/analysis';
```

**禁止：**

```ts
import { StepDetail } from '@/features/analysis/components/StepDetail';     // 禁止
import { useAnalysisStore } from '@/features/analysis/model/store';         // 禁止
import { fetchAnalysis } from '@/features/analysis/services/analysisApi';   // 禁止
```

**为什么：**

- `index.ts` 是每个 feature 对外的**唯一契约面**。外部只看得到应该看的东西，feature 内部随时可以重构，外部零感知。
- 没有这条，再好的目录结构都会在 6 个月后退化成"谁想用谁都能点进去拿"的意面。

**补充约束：**

- `features/<A>/` 不允许 `import` 来自 `features/<B>/` 的内部文件，只能经由 `index.ts`。
- `features/*` **绝对不允许** import `app/*`（方向反了）。
- `shared/*` **绝对不允许** import `features/*` 或 `app/*`（shared 是底层，永远不知道上层业务）。

**依赖方向一图：**

```text
  app/  ──── 可以依赖 ───▶  features/  ──── 可以依赖 ───▶  shared/
   ▲                                                         │
   │                                                         │
   └─────────────── 禁止反向依赖 ◀─────────────────────────┘
```

---

## 3. 机械化检查（零配置成本，立刻可加）

这三条纪律都可以用 ESLint 的内置或社区规则强制，**不需要新工具**。建议在 `frontend/` 的 ESLint 配置里加下面几条。若短期未加，仍应写进 PR 模板作为 review checklist。

### 3.1 `no-restricted-imports` 落实纪律 3

```jsonc
{
  "rules": {
    "no-restricted-imports": [
      "error",
      {
        "patterns": [
          {
            "group": ["@/features/*/components/*", "@/features/*/hooks/*", "@/features/*/services/*", "@/features/*/model/*"],
            "message": "跨 feature 访问请只经由 @/features/<name> 的 index.ts"
          },
          {
            "group": ["@/app/*"],
            "message": "features/ 和 shared/ 不允许反向依赖 app/"
          }
        ]
      }
    ]
  }
}
```

### 3.2 用 `eslint-plugin-boundaries`（可选，更严格）

若未来规模继续扩大，可以引入 `eslint-plugin-boundaries` 把"app → features → shared"的单向依赖机械化。此前保持 `no-restricted-imports` 已经够用。

### 3.3 用目录级 `eslint` overrides 落实纪律 1

```jsonc
{
  "overrides": [
    {
      "files": ["src/features/*/model/**/*.{ts,tsx}"],
      "rules": {
        "no-restricted-imports": [
          "error",
          {
            "paths": [
              { "name": "react", "message": "features/*/model 不允许依赖 React" },
              { "name": "react-router-dom", "message": "features/*/model 不允许依赖 React Router" },
              { "name": "antd", "message": "features/*/model 不允许依赖 AntD" }
            ]
          }
        ]
      }
    }
  ]
}
```

### 3.4 用目录级 `eslint` overrides 落实纪律 2

```jsonc
{
  "overrides": [
    {
      "files": ["src/shared/api/**/*.{ts,tsx}"],
      "rules": {
        "no-restricted-globals": [
          "error",
          { "name": "document", "message": "shared/api 不允许直接访问 document，请走 shared/storage" },
          { "name": "window", "message": "shared/api 不允许直接访问 window，请走 shared/storage" },
          { "name": "localStorage", "message": "shared/api 不允许直接访问 localStorage，请走 shared/storage" }
        ]
      }
    }
  ]
}
```

---

## 4. 常见边界情形的判定

### 4.1 一个组件被多个 feature 用，放在哪？

先按下面顺序判断：

1. 它是否承载**具体业务含义**（例如"conversation 选择器"）？→ 属于主用 feature，放 `features/<主>/`；其他 feature 通过 `features/<主>/index.ts` 引用。
2. 它是否是**与业务无关的视觉原子**（例如 `EmptyState`、`StatusTag`）？→ 放 `shared/ui/`。
3. 介于两者之间？→ 默认**放主用 feature**，等出现第 3 个 feature 用它再提升到 `shared/ui/`。

**反例：** 一出现复用苗头就往 `shared/ui/` 塞，最终 `shared/ui/` 堆满"半业务半通用"的组件，永远无法复用。

### 4.2 一个类型既是 API 契约又是 UI 视图状态，放哪？

- **后端返回的原始契约** → `shared/types/`（纯 mirror，不要带 UI 字段）。
  - **唯一来源**：各后端服务的 `/openapi.json`（见 [`./backend.md §9`](./backend.md)）。任何**不来自 OpenAPI** 的类型不允许进入 `shared/types/`——它们要么是 feature 内部类型（放 `features/<name>/model/types.ts`），要么是纯工具类型（放 `shared/lib/`）。
  - 短期允许手写镜像 OpenAPI，但每个文件顶部必须注明对应的 OpenAPI schema 名和所属服务；长期走代码生成（参见 `.notes/todolist.md §9`）。
  - **按服务命名空间组织**：`shared/types/auth/`、`shared/types/analysis/` 各自承载对应服务的 OpenAPI 镜像；每个服务的契约类型**独立成文件**（如 `shared/types/auth/User.ts`），避免跨服务混放一个 `types.d.ts` 造成"改一个服务的契约动另一个服务的文件"。
- **跨 feature 复用的原始契约类型**（例如 `User` 被 `features/auth` / `features/conversation` / `features/report` 同时消费）：
  - **统一**从 `shared/types/<service>/` 导入：`import type { User } from '@/shared/types/auth'`。
  - **禁止** feature 内部为共享类型做本地拷贝（`features/conversation/model/types.ts` 里复制一份 `User`）——OpenAPI 演进时会漂。
  - **禁止**通过某个"主用 feature"的 `index.ts` 再导出给其他 feature（例如 `features/auth` barrel 转出 `User`），这会让 `features/conversation → features/auth` 形成跨 feature 依赖，违反纪律 3 的依赖方向。
- **feature 在原始契约类型之上加 UI 字段**时：用 `type ViewUser = User & { expanded: boolean }` 或 `Pick<User, 'id' | 'email'>` 在 `features/<name>/model/types.ts` 里**本地派生**；派生类型**不回写** `shared/types/`。
- 禁止把 "API 契约 + UI 派生字段" 混在同一个 type 里，这是未来契约漂移最常见的温床。

### 4.3 `shared/ui/` 收什么、拒什么

**收：**

- AntD 没有、且确实被 2 个以上 feature 复用的复合组件
- 少量带"产品视觉语言"的壳组件（例如包了 AntD `Tag` 的 `StatusTag`，用来统一颜色/语义）

**拒：**

- 单纯对 `antd/Button`、`antd/Modal` 的原样 re-export（只会在 AntD 升级时带来维护成本）
- 任何带业务语义的组件（`AnalysisStatusBadge` 属于 analysis，不属于 shared）

### 4.4 页面放哪：features 内 vs app/pages？

**统一放 `app/pages/`**，每个页面只做两件事：

1. 选择 layout；
2. 从 features 拼视图块。

**理由：**

- `Home`、`Reports` 这类页面天然是多 feature 的装配；塞进任何单一 feature 都会污染边界。
- 路由器未来若切换（TanStack Router / Next 等），只需重写 `app/router/` 与 `app/pages/`，features 零改动。

### 4.5 跨 feature 的 hook 放哪？

- 如果它**只调度 feature 暴露出来的东西**（例如 `useDashboardData` 同时读 conversation + analysis）→ 放 `app/pages/` 里对应页面的 `hooks/` 子目录，或 `app/hooks/`（按需新建）。
- **绝对不要放进某一个 `features/*/hooks/`**，那会造成 feature 之间的隐性双向依赖。

---

### 4.6 与 gateway / backend 的契约对齐（硬约束）

前端代码要按 [`./gateway.md`](./gateway.md) 与 [`./backend.md`](./backend.md) 定义的跨层契约工作。下面列出**直接决定前端代码形状**的那几条，出现在 PR 里违反即 block：

- **`axios.baseURL` 唯一合法值是 `''`**（空字符串），业务调用统一写完整路径 `'/api/v1/...'`。**禁止绝对 URL**（`http://localhost:9080` / `http://gateway:9080`），**禁止 `'/api'` 前缀写法**。
  - 为什么不允许 `'/api'`：URL 前缀 `/api/v1/` 是跨前后端共同契约，不会独立演化；让业务调用里直接出现完整路径，grep 全路径定位接口成本最低。一个仓库两种写法并存、"团队口头统一"迟早会漂——硬钉死一种最简单。
  - 浏览器永远只通过同域 gateway（`/`）访问 API，绝对 URL 会同时破坏开发代理、cookie 作用域与 CORS 零配置三件事。
  - 若本地联调需要指向另一套 compose，走 Vite `server.proxy` 或 gateway 端口映射，不改源码。
- **所有需要鉴权的请求必须 `withCredentials: true`**；CSRF 头 `X-XSRF-TOKEN` 由 `shared/api/client.ts` 拦截器统一注入，业务代码不手写。
- **响应解析按 `backend.md §6.0` 信封**：成功读 `data.data`，失败读 `data.details`。
  - 错误子码以 **`data.details.errorCode`** 为准（SCREAMING_SNAKE_CASE 字符串），**不允许**从顶层 `code` 读业务码——顶层 `code` 等于 HTTP 状态码，不承载业务信息。
  - 无 `details.errorCode` 时按 HTTP 状态（`401` → 跳登录，`403` → CSRF 重取，`5xx` → 通用兜底）处理，不要猜测字段。
  - **禁止依赖 `apiVersion` 字段** —— 它已从响应信封中移除，URL 前缀 `/api/v1/` 是唯一的版本载体。
- **接入面错误码按基础设施前缀匹配**（严禁按字符串子串匹配业务含义）：
  - `GATEWAY_AUTH_REQUIRED`（401）→ 跳登录或触发静默 refresh 流程。
  - `GATEWAY_CSRF_INVALID`（403）→ 重新拉 `XSRF-TOKEN` 后重试一次；仍失败则通用错误 UI。
  - `GATEWAY_INTROSPECT_UNAVAILABLE`（503）→ 通用 5xx 兜底 UI + 可手动重试按钮。
  - `GATEWAY_IDENTITY_MISSING`（500）→ 直接触发通用 5xx 兜底 UI，**不要**"静默重试"或"跳登录"——这是接入面事故，重试无意义、跳登录会掩盖故障。
  - `INTERNAL_AUTH_FAILED`（500）→ 对前端而言等同未知 5xx（该错误码只会出现在 internal 路径，前端理论上不该看到；看到即异常）。
- **`X-Request-Id` 在 `shared/storage/requestId.ts` 生成并注入**；错误 toast 的角落里展示该 id（只读、可复制），便于用户复述给支持侧。

这些约束只会出现在 `shared/api/` 与 `shared/storage/` 两层；feature 代码应该感受不到协议细节，只拿到已解析好的业务 `data` 或已分类的错误对象。

---

## 5. 显式约束：什么**不要做**（硬约束）

为了保证"未来好维护"不会偷偷变成"现在就付出很多工程税"，下面这些事项是 PR review 层面的**硬约束**（性质同 §4.6）——在可预见的未来都不做，违例项需要在 PR 描述里单独 justify 并由 review 明确放行，默认拒绝合并：

- **不新建 `packages/*`、不引入 pnpm/npm workspaces、不引入 turbo/nx**；只保留 `frontend/` 作为一个普通 npm 项目。
- **不新建 `infrastructure/` 层**：纯 SPA 场景下它与 `shared/` 是冗余的。若未来真的引入 Web Worker / WASM / ServiceWorker 并出现"平台耦合"，届时再拆，不预建空层。
- **不写"未来支持多端"类注释或 TODO**：结构本身已经让未来抽离成本足够低；冗余注释反而会误导新同学。
- **不把"feature A 调 feature B 的内部文件"合法化**：即使是一次性的 hotfix，也应通过在 B 的 `index.ts` 上补一条暴露。
- **不让 frontend 容器在 `docker-compose.yml` 里 `ports` 对外暴露端口**：frontend 容器与业务服务同等，**只 `expose` 不 `ports`**，浏览器永远只通过 gateway 访问（见 [`./gateway.md §2.4`](./gateway.md)）。
- **不在 frontend 容器的 `nginx.conf` 里下发 CSP / HSTS / XFO 等安全响应头**：这些头由 gateway 一层统一下发（见 [`./gateway.md §6.6`](./gateway.md)）。`index.html` 的 `Cache-Control: no-store` 仍配在前端 nginx（属于静态分发层职责）。

---

## 6. 新增一个 feature 的标准动作

1. 在 `src/features/` 下新建目录（例如 `features/notification/`）。
2. 建好 `components/ hooks/ services/ model/` 子目录与 `index.ts`。
3. `model/types.ts` 写入 feature 内部类型；若需要后端契约类型，去 `shared/types/` 加。
4. `services/` 写 API 调用封装，只依赖 `shared/api/`。
5. `model/store.ts` 写 Zustand slice 或定义 TanStack Query key。
6. `hooks/` 组装 `services/` 与 `model/`。
7. `components/` 写业务组件，只依赖本 feature 的 `hooks/` / `model/` / `services/`。
8. 在 `index.ts` 中**只暴露外部需要的符号**（通常是若干 hooks 和若干组件，以及一两个类型）。
9. 在 `app/router/` 或 `app/pages/` 里装配成页面。

完成后自检三条纪律全部成立，即可提交。

---

## 7. 参考

- 网关开发指南：[`./gateway.md`](./gateway.md)
- 后端接入契约：[`./backend.md`](./backend.md)
- 设计决策沿革：[`.notes/engineering-design.md`](../../.notes/engineering-design.md)（冲突时以本文档为准）
- 当前可执行 backlog：[`.notes/todolist.md`](../../.notes/todolist.md)
- 研究愿景（非工程事实）：[`.notes/paper-outline.md`](../../.notes/paper-outline.md)
