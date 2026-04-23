# 前端开发指南

本文档固定 Pixels Rover **单 Web 前端** 的目录契约与开发纪律。

- 适用范围：仓库中 `frontend/` 目录（即 Web SPA）。
- 设计前提：产品长期只保留一种客户端（网页），**不会**拆 `apps/mobile`、`apps/desktop`，**不会**引入 `packages/*` 共享层或 monorepo 工具链。
- 文档目的：让任何新同学在不读历史对话的情况下，也能按一致的方式加代码；同时让结构本身在未来万一需要多端时可以低成本抽离，而不需要现在付出多端的工程税。
- 以代码事实为准：若代码与本文档出现漂移，优先修正代码或及时更新本文档。

---

## 1. 目录结构（唯一正确形态）

> 本节描述**唯一正确形态**。仓库已固定 `frontend/` 为根级单 Web 前端目录；本文件内所有路径引用（`frontend/src/...` / `@/features/...`）即为代码事实。`src/` 内部从 `pages + components + services + stores + ...` 向 `app + features + shared` 三层迁移已完成，沿革背景见 `.notes/engineering-design.md`。

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
│   ├── Foo.tsx
│   └── Foo.test.tsx   (colocated) — 或同目录 __tests__/Foo.test.tsx
├── hooks/             React hook；调用 services 并绑定 model
│   ├── useBar.ts
│   └── useBar.test.ts (colocated)
├── services/          纯函数 / 类：API 调用封装、SSE 订阅、业务计算
│   ├── bazApi.ts
│   └── bazApi.test.ts (colocated)
├── model/
│   ├── types.ts       feature 内部业务类型（与后端契约类型区分）
│   ├── store.ts       Zustand slice 或 TanStack Query key 定义
│   ├── store.test.ts  (colocated)
│   └── selectors.ts   对 store 的派生计算
└── index.ts           对外 barrel：只暴露 hooks / 组件 / 类型；不暴露内部文件
```

### 1.1.1 测试文件 colocated 硬规则

- **测试文件与被测源文件同目录**，命名为 `<name>.test.ts(x)` 或放进就近的 `__tests__/` 子目录。**禁止**集中在某个顶级 `src/__tests__/` 或 `src/tests/` 目录。
- 搬代码 PR 必须同步搬对应测试文件；**禁止**出现"源文件在 `features/analysis/` 新位置、测试仍留在 `src/__tests__/` 旧位置"的中间态。该硬规则与纪律 3（跨 feature 只经由 barrel）同源——测试对 feature 内部的依赖如果跨目录存在，重构 feature 时测试会变成"看不见的外部引用者"而卡住重构。
- 测试文件与源文件**共享 feature 边界**：`features/analysis/**/ *.test.ts(x)` 只能 import 本 feature 的内部符号 + `shared/*` + 其他 feature 的 `@/features/<name>` barrel（与 feature 生产代码的依赖规则完全一致）。
- `features/*/model/**/*.test.ts(x)` 豁免纪律 1 对 React 的禁令——测试可以用 `@testing-library/react` 等工具渲染 hook/组件；但被测的 `model/` 源文件本身**仍然禁止** import React（见纪律 1）。

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

### 3.0 Lint 规则的合规判据（适用于本节 3.1 / 3.3 / 3.4 / 3.5 的**所有**规则）

本节配置的任一条 ESLint 规则，合规判据都是"**规则能实际触发**"，不是"**规则配上了**"：

- 规则落地 PR **必须**在 PR 描述里附一次"故意构造违规代码 → 跑 lint → 规则报错"的验证记录（截图或复制命令输出），随后再删除违规代码。
- 规则"配上了但一次都不触发"（通常由 ESLint 选择器写错、TypeScript 全局声明绕过、目录 glob 覆盖不到等原因导致）**与规则未配等价**，不算合规。
- 合规验证后，应该**保留一个 `*.lint-assertion.ts.skip` 之类的示例文件**（或直接在 PR 描述里固化反例代码片段），便于未来 lint 升级时快速回归验证规则仍有效。

该判据对所有目录级 overrides 规则（§3.3 纪律 1、§3.4 纪律 2、§3.5 协议头字面量）同样适用；§3.4 最末尾的"合规判定"段落是本节的特例引用，不是专属 lint-2 的放宽。

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

**关于 `no-restricted-globals` 在 TypeScript 工程里的 caveat（必须阅读）**：

`no-restricted-globals` 对 ESLint 自己识别为"全局变量"的 identifier 才会触发。在 TypeScript 项目下，`document` / `window` / `localStorage` / `sessionStorage` 都是由 `lib.dom.d.ts` 声明的全局类型——**ESLint 实测对这类"已在 DOM lib 里声明的全局"通常会放行**，最终表现为"规则配上了、但一次都不触发"。这条规则是否真的把 `shared/api` 的浏览器副作用拦住，**必须以"规则实际触发"为合格标准**，而不是"规则写进配置了"就算数。

两种兜底落地路径，按推荐度排列：

1. **推荐**：改用 `no-restricted-syntax` + AST 选择器，直接匹配 `MemberExpression` 上的对象名：

    ```jsonc
    {
      "overrides": [
        {
          "files": ["src/shared/api/**/*.{ts,tsx}"],
          "rules": {
            "no-restricted-syntax": [
              "error",
              {
                "selector": "MemberExpression[object.name=/^(document|window|localStorage|sessionStorage)$/]",
                "message": "shared/api 不允许直接访问 document/window/localStorage/sessionStorage，请走 shared/storage"
              }
            ]
          }
        }
      ]
    }
    ```

2. 引入 `eslint-plugin-boundaries` 做"目录级硬墙"，把 `shared/api/` 整个隔离在"只能 import `shared/storage/` 暴露的工具"的维度上。

**合规判定**：新增 PR 落地该规则后，必须在本地构造一个违规调用（例如在 `src/shared/api/client.ts` 临时写 `document.cookie = 'x=1'`），跑 `pnpm lint` / `npm run lint`，**确认规则报错**后再删除违规代码。规则"配上但不触发"不合规。

### 3.5 用 `no-restricted-syntax` 禁止业务层手写协议头字面量

纪律 2 的延伸：`X-XSRF-TOKEN` / `X-Request-Id` / `Authorization` 等协议头的字面量赋值**只允许出现在 `src/shared/api/**`** 内部（含 `shared/api/sse/**` 的 SSE 客户端——SSE 基于 `fetch` 手动构造 header 时复用 `shared/api` 暴露的 `buildCommonHeaders()`，仍属 shared 网络层内部）。在 `features/` / `entities/` / `services/` 等任何其他层里出现这些字面量赋值一律视为"业务代码手写请求头"——违反 `§4.6` 的跨层契约。

机械化规则：

```jsonc
{
  "overrides": [
    {
      "files": ["src/**/*.{ts,tsx}"],
      "excludedFiles": ["src/shared/api/**/*.{ts,tsx}"],
      "rules": {
        "no-restricted-syntax": [
          "error",
          {
            "selector": "Literal[value=/^(X-XSRF-TOKEN|X-Request-Id|Authorization)$/i]",
            "message": "协议头字面量只允许出现在 shared/api/**；业务层通过 shared/api 暴露的 client / buildCommonHeaders 间接使用"
          }
        ]
      }
    }
  ]
}
```

- **判据是目录路径，不是字符串子串全仓禁用**——`shared/api/**` 内部需要合法写这些字面量，全仓禁用会误伤 SSE 客户端。
- 与 `§4.6` 的 SSE 豁免条款配合使用：feature 层通过 `shared/api` 暴露的封装间接消费 header，不感知字面量。

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
  - 短期允许手写镜像 OpenAPI，但每个文件顶部必须注明对应的 OpenAPI schema 名和所属服务；长期走代码生成。
  - **按服务命名空间组织**：`shared/types/auth/`、`shared/types/analysis/` 各自承载对应服务的 OpenAPI 镜像；每个服务的契约类型**独立成文件**（如 `shared/types/auth/User.ts`），避免跨服务混放一个 `types.d.ts` 造成"改一个服务的契约动另一个服务的文件"。
- **跨 feature 复用的原始契约类型**（例如 `User` 被 `features/auth` / `features/conversation` / `features/report` 同时消费）：
  - **统一**从 `shared/types/<service>/` 导入：`import type { User } from '@/shared/types/auth'`。
  - **禁止** feature 内部为共享类型做本地拷贝（`features/conversation/model/types.ts` 里复制一份 `User`）——OpenAPI 演进时会漂。
  - **禁止**通过某个"主用 feature"的 `index.ts` 再导出给其他 feature（例如 `features/auth` barrel 转出 `User`），这会让 `features/conversation → features/auth` 形成跨 feature 依赖，违反纪律 3 的依赖方向。
- **跨服务通用协议类型**（响应信封 `ApiResponse<T>`、接入面 `ErrorCode` 联合类型、`RequestId` 相关类型）：
  - **统一放 `src/shared/types/common.ts`**（不按服务命名空间拆）——这些是跨前后端的**协议层常量**，不属于任何单一服务的 OpenAPI。按服务命名空间拆会迫使每个服务各写一份 `ApiResponse<T>`，彼此独立演化即违约。
  - `ApiResponse<T>` 的字段形状以 [`./backend.md §6.0`](./backend.md) 为权威来源；`ErrorCode` 联合类型的基础设施前缀部分以 [`./backend.md §6.3.1`](./backend.md) 的错误码注册表为权威来源，业务领域前缀部分由各服务 `shared/types/<service>/` 下的 OpenAPI 镜像独立贡献并在 `common.ts` 里以 `type ErrorCode = InfraErrorCode | AuthErrorCode | AnalysisErrorCode | ...` 合并（合并硬规则与审计要求见 [`./backend.md §6.3.2`](./backend.md)；**新增业务前缀时必须三处同改**：对应服务 OpenAPI enum → `shared/types/<service>/ErrorCode.ts` → `common.ts` 的 `ErrorCode` union，任一漏改会让该错误码在前端分流时静默走通用 5xx 兜底）。
  - 这类文件**不写后端 OpenAPI 镜像字段**（没有 `User` / `Conversation` 等领域类型），只写协议层抽象。判据：若未来新增的服务完全不需要这个类型，它就不属于 `common.ts`。
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
  - **SSE / `fetch` 场景的豁免与责任分配**：浏览器原生 `EventSource` 无法携带自定义头，项目已改用"基于 `fetch(..., { credentials: 'include' })` 的流式客户端"（位于 `shared/api/sse/`）。该客户端**在 SSE 层内部**复用 `shared/api/client.ts` 暴露的"只读请求头构造函数"（`buildCommonHeaders()`）来拼 `X-XSRF-TOKEN` / `X-Request-Id`；**这不是"业务代码手写请求头"的反例**，而是"shared 网络层内部复用 shared 网络层工具"的合法形态。
  - 判定规则：**拼 header 的调用点必须位于 `shared/api/**`**。feature / entities / services 层仍**严禁**出现 `X-XSRF-TOKEN` / `X-Request-Id` / `Authorization` 等字面量的手写赋值，由 ESLint `no-restricted-syntax` 规则兜底（见 §3.5）。
  - **SSE 失败模式与 heartbeat 约定（硬规则）**：SSE 在浏览器端不是"连上就永远畅通"的理想通道。下列三类失败模式在生产必然出现，`shared/api/sse/` 的客户端实现**必须**显式处理：
    1. **Chrome 后台 tab suspend**：浏览器在后台 tab 休眠时可能暂停 `fetch` 流式读取，表现为"30 秒内完全无数据"；
    2. **Safari < 16.4 的 `fetch` 流不可用**：降级表现为一次性读完整 body 才回调，SSE 语义失效；客户端需 feature-detect，若不支持则明确降级到一次性请求或显示"浏览器不支持实时更新"；
    3. **企业代理 chunked 超时断连**：部分企业代理对长连接做 60~120s 静默断连，表现为"流中段被 abort"。

     针对这三类的统一兜底契约（与 [`./backend.md §6.6`](./backend.md) 服务端 SSE 契约对齐）：

    - **服务端每 15 秒**发一条 SSE 注释帧 `: keep-alive\n\n`（见 `backend.md §6.6`）——这是跨服务硬数值。
    - **前端按 30 秒无数据阈值判定断流**（即连续错过 2 次 heartbeat），此时通过 `ensureRequestId()` **复用同一 request-id** 触发一次自动重连（带 `Last-Event-Id` 头实现位点恢复）；
    - **自动重连仍失败**时，降级为通用 5xx 兜底 UI，提示用户手动刷新；**不做**无限指数退避重连——它会把"服务端确实挂了"的事故掩盖成"前端 UI 看起来还在转圈"。
    - 收到 `event: error` 帧（见 `backend.md §6.6`）时，按帧内 `data.details.errorCode` 走与普通 HTTP 错误一致的分流（`GATEWAY_AUTH_REQUIRED` → 跳登录等）；**不走** 自动重连路径。
- **响应解析按 `backend.md §6.0` 信封**：成功读 `data.data`，失败读 `data.details`。
  - 错误子码以 **`data.details.errorCode`** 为准（SCREAMING_SNAKE_CASE 字符串），**不允许**从顶层 `code` 读业务码——顶层 `code` 等于 HTTP 状态码，不承载业务信息。
  - 无 `details.errorCode` 时按 HTTP 状态（`401` → 跳登录，`403` → CSRF 重取，`5xx` → 通用兜底）处理，不要猜测字段。
  - **禁止依赖 `apiVersion` 字段** —— 它已从响应信封中移除，URL 前缀 `/api/v1/` 是唯一的版本载体。
  - **HTTP status 是分流的唯一依据（硬规则）**：`data.code`（响应信封顶层 `code`）与实际 HTTP status 理论上恒等（见 `backend.md §6.0`）。任何一方出现"HTTP 是 200 但 `data.code` 是 400"或反之的形态一律视为 **server bug**——前端**不**做"body 说错了就当错"的适配补丁，**一律按 HTTP status 方向处理**，同时 `console.error` 一次（带 requestId、路径、两边的 code 值），便于在 QA / 生产被捕获并修回服务端。**禁止**让业务层拿到两种不一致的分流结果，否则一次协议漂移会在 UI 层再漂移一层。
- **接入面错误码按基础设施前缀匹配**（严禁按字符串子串匹配业务含义）：
  - `GATEWAY_AUTH_REQUIRED`（401）→ 跳登录或触发静默 refresh 流程。
  - `GATEWAY_CSRF_INVALID`（403）→ 重新拉 `XSRF-TOKEN` 后重试一次；仍失败则通用错误 UI。
  - `GATEWAY_INTROSPECT_UNAVAILABLE`（503）→ 通用 5xx 兜底 UI + 可手动重试按钮。
  - `GATEWAY_IDENTITY_MISSING`（500）→ 直接触发通用 5xx 兜底 UI，**不要**"静默重试"或"跳登录"——这是接入面事故，重试无意义、跳登录会掩盖故障。
  - `INTERNAL_AUTH_FAILED`（500）→ 对前端而言等同未知 5xx（该错误码只会出现在 internal 路径，前端理论上不该看到；看到即异常）。
- **`X-Request-Id` 在 `shared/storage/requestId.ts` 生成并注入**；错误 toast 的角落里展示该 id（只读、可复制），便于用户复述给支持侧。
  - **职责边界（硬规则）**：id 的**生成与本地缓存**职责属于 `shared/storage/requestId.ts`（纯浏览器副作用：`crypto.randomUUID()` / `localStorage` / 会话内单例缓存等）；把 id **绑定到 axios config 对象或 fetch 请求头**的职责属于 `shared/api/`（axios 拦截器 / SSE 客户端的 `buildCommonHeaders`）。**两层不重叠**：`shared/storage/` 不 import axios，也不感知 fetch / `Request` API；`shared/api/` 不直接用 `crypto.randomUUID()` 或读写 storage，只调用 `ensureRequestId()` 等纯函数入口。历史上把"生成 id"写到 axios 拦截器里是跨端复用和 SSR 兼容的最大障碍，也是 §3 纪律 2 的典型违例形态——任何混两层的 PR 一律打回。

这些约束只会出现在 `shared/api/` 与 `shared/storage/` 两层；feature 代码应该感受不到协议细节，只拿到已解析好的业务 `data` 或已分类的错误对象。

- **手写契约镜像文件的顶部元数据（硬规则）**：`frontend/src/shared/types/` 下任何"后端契约镜像"类型文件（当前形态：`infra.ts`、`auth/ErrorCode.ts`、`analysis/ErrorCode.ts`、`api.d.ts`、`conversation.d.ts`、`schema.d.ts`、`sse.d.ts`、`user.d.ts`、`analysis.d.ts`）——即凡是"手工与后端保持一致"的 TS 类型文件，**必须**在文件顶部 JSDoc 里显式写清以下两个字段，便于 `scripts/check-contracts.py` 与 review 快速定位 SSOT：
  1. **owning service**：该契约归属哪个服务（`auth-service` / `assistant-service` / `gateway`；`shared` 仅限真正跨服务的信封类型，默认禁用）。
  2. **Source of truth（二选一）**：
     - **OpenAPI schema 名**，形如 `services/<svc>/openapi.json#/components/schemas/<SchemaName>`，或
     - **SSOT 源文件 + 符号**，形如 `gateway/error-codes.json::code`、`services/auth-service/.../ErrorCodeName.java::AUTH_*`、`services/assistant-service/app/error_codes.py::ANALYSIS_*`。
     如果两者都有，优先 OpenAPI schema——它是将来自动生成的锚点；与 Java/Python 常量的对齐由 `check-contracts.py` 的双向一致性断言（`frontend-auth-union-equals-java-source` / `frontend-analysis-union-equals-python-source`）兜底。

  模板：

  ```ts
  /**
   * <一句话用途>.
   *
   * owning-service: auth-service
   * source-of-truth: services/auth-service/src/main/java/io/pixelsdb/pixels/rover/config/common/ErrorCodeName.java::AUTH_*
   *   (long-term mirror of services/auth-service/openapi.json#/components/schemas/ApiErrorDetails/properties/errorCode/enum)
   */
  export type AuthErrorCode = /* ... */;
  ```

  违例条件（PR 层面拒绝合并）：
  - 新加一个 `frontend/src/shared/types/<svc>/*.ts` / `.d.ts` 文件没写这两个字段；
  - owning service 写的是"`shared`"但契约实际属于某个具体服务；
  - source-of-truth 的路径对不上（文件 / 符号不存在）。

  已有文件的迁移由 §10 条 10 的一次性 PR 集中做（`infra.ts` / `auth/ErrorCode.ts` / `analysis/ErrorCode.ts` 已符合；`.d.ts` 手写镜像待补）。


---

## 5. 显式约束：什么**不要做**（硬约束）

为了保证"未来好维护"不会偷偷变成"现在就付出很多工程税"，下面这些事项是 PR review 层面的**硬约束**（性质同 §4.6）——在可预见的未来都不做，违例项需要在 PR 描述里单独 justify 并由 review 明确放行，默认拒绝合并：

- **不新建 `packages/*`、不引入 pnpm/npm workspaces、不引入 turbo/nx**；只保留 `frontend/` 作为一个普通 npm 项目。
- **不新建 `infrastructure/` 层**：纯 SPA 场景下它与 `shared/` 是冗余的。若未来真的引入 Web Worker / WASM / ServiceWorker 并出现"平台耦合"，届时再拆，不预建空层。
- **不写"未来支持多端"类注释或 TODO**：结构本身已经让未来抽离成本足够低；冗余注释反而会误导新同学。
- **不把"feature A 调 feature B 的内部文件"合法化**：即使是一次性的 hotfix，也应通过在 B 的 `index.ts` 上补一条暴露。
- **不让 frontend 容器在 `docker-compose.yml` 里 `ports` 对外暴露端口**：frontend 容器与业务服务同等，**只 `expose` 不 `ports`**，浏览器永远只通过 gateway 访问（见 [`./gateway.md §2.4`](./gateway.md)）。
- **不在 frontend 容器的 `nginx.conf` 里下发 CSP / HSTS / XFO 等安全响应头**：这些头由 gateway 一层统一下发（见 [`./gateway.md §6.6`](./gateway.md)）。
- **`index.html` 必须在 frontend nginx 下发 `Cache-Control: no-store`（硬规则）**：写法为 `location = /index.html { add_header Cache-Control "no-store" always; try_files $uri =404; }`。这是"静态分发层职责"而非网关职责。理由：Vite 构建产物里只有两个 URL 族——(1) 内容哈希化的资源 `assets/index-<hash>.{js,css}`，内容即 URL，所以安全地 `public, immutable`；(2) 作为唯一入口的 `index.html`，其内容（对资源 bundle hash 的引用）**每次部署都变**。若中间缓存（浏览器 / 公司代理 / CDN 边缘）持有旧 `index.html`，它会继续指向发布后已被删除的 `assets/index-<old>.js`，用户看到白屏或 404 直到缓存过期。`always` 修饰符必须加——没有它 `add_header` 会在非 2xx/3xx 状态下被 nginx 静默丢弃，让错误路径把 stale-index 风险偷偷带回来。该条由 `scripts/check-contracts.py::frontend-index-html-no-store` 做长期回潮防线。
- **SPA 深链接 fallback 必须配在 frontend 容器的 `nginx.conf`**（硬规则，见 [`./gateway.md §2.4`](./gateway.md)）：`try_files $uri $uri/ /index.html;` 或等价形态。HTML5 history routing 下，刷新 `/reports/abc` 这类深链接没有 fallback 会 404。**禁止**把 fallback 配在 gateway 层（用 `proxy-rewrite` 把 404 改写为 `/index.html`）——gateway 不理解 SPA 路由形态，未来引入 SSR / SSG 时会成为改造阻碍。

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
9. **测试文件与源文件同目录 colocated**（见 §1.1.1），每个 `components/ hooks/ services/ model/` 下对应的 `*.test.ts(x)` 与源文件就近放置；**禁止**集中在顶级 `src/__tests__/` 目录。
10. 在 `app/router/` 或 `app/pages/` 里装配成页面。

完成后自检三条纪律全部成立 + 测试文件全部 colocated，即可提交。

---

## 7. 参考

- 网关开发指南：[`./gateway.md`](./gateway.md)
- 后端接入契约：[`./backend.md`](./backend.md)
