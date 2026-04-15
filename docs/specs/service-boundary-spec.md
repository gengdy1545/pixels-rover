# Pixels Rover 服务边界规范

## 1. 目标

本文档定义 Pixels Rover 各服务的职责边界、API 路由归属和跨服务通信规则，确保：

- 前端开发者清晰知道"什么请求发给谁"
- 后端开发者清晰知道"什么功能放在哪个服务"
- 新增功能时有明确的归属判断标准
- 服务拆分/合并时有据可依

## 2. 服务全景

```
┌─────────────────────────────────────────────────────────────────┐
│                     API Gateway (Nginx + NJS)                   │
│                        Unified Entry (port 80)                  │
│  ┌──────────┬──────────┬──────────┬──────────┬───────────────┐  │
│  │ /api/v1/ │ /api/v1/ │ /api/v1/ │ /api/v1/ │   /api/v1/    │  │
│  │  auth/*  │  chat/*  │ query/*  │metadata/*│  analysis/*   │  │
│  │          │          │text-to-sql│         │  semantic/*   │  │
│  │          │          │          │          │  backends/*   │  │
│  └────┬─────┴────┬─────┴────┬─────┴────┬─────┴───────┬───────┘  │
│       │          │          │          │             │           │
│       ▼          ▼          ▼          ▼             ▼           │
│  auth-service  auth-service  Pixels   Pixels   analysis-service │
│   (8081)       (8081)       Server   Server      (8090)         │
│               [short-term]  [direct] [direct]                   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 服务清单

| 服务 | 技术栈 | 内部端口 | 职责概述 |
|------|--------|----------|----------|
| **API Gateway** | Nginx + NJS | 80 | 统一入口、JWT 鉴权透传、Cookie 管理、CSRF 验证、限流、CORS、审计日志 |
| **auth-service** | Java / Spring Boot | 8081 | 身份认证、会话管理、聊天历史（短期） |
| **analysis-service** | Python / FastAPI | 8090 | LLM 分析、语义层、存储后端管理 |
| **Pixels Server** | 外部服务 | 可配置 | 数据查询引擎（元数据查询、SQL 执行） |
| **Text2SQL Service** | 外部服务 | 可配置 | 自然语言转 SQL |
| **Frontend** | React / Vite | 80 (Nginx) | Web UI、SPA 静态资源 |

## 3. 域划分

### 3.1 认证域（Authentication Domain）

**归属服务**：auth-service (Java)

**路由前缀**：`/api/v1/auth/*`

**职责范围**：
- 用户注册、登录、登出
- 验证码生成与校验
- JWT 签发、刷新、撤销
- 会话管理（多设备会话列表、单设备登出、全设备登出）
- 用户信息查询（`/me`、`/user-info`）
- JWKS 公钥端点

**API 端点清单**：

| 方法 | 路径 | 说明 | 认证要求 |
|------|------|------|----------|
| POST | `/api/v1/auth/login` | 登录 | 否 |
| POST | `/api/v1/auth/register` | 注册 | 否 |
| GET | `/api/v1/auth/captcha` | 获取验证码 | 否 |
| POST | `/api/v1/auth/refresh` | 刷新 token | 否（需 refresh token） |
| GET | `/api/v1/auth/me` | 当前用户信息（轻量） | 是 |
| GET | `/api/v1/auth/user-info` | 当前用户详细信息 | 是 |
| GET | `/api/v1/auth/jwks` | RSA 公钥 | 否 |
| GET | `/api/v1/auth/sessions` | 会话列表 | 是 |
| POST | `/api/v1/auth/logout` | 登出当前会话 | 是 |
| POST | `/api/v1/auth/logout-all` | 登出其他会话 | 是 |
| DELETE | `/api/v1/auth/sessions/{sessionId}` | 撤销指定会话 | 是 |

**不应包含的职责**：
- ❌ 数据查询/分析
- ❌ 元数据管理
- ❌ LLM 调用
- ❌ 存储后端管理

### 3.2 分析域（Analysis Domain）

**归属服务**：analysis-service (Python)

**路由前缀**：`/api/v1/analysis/*`、`/api/v1/semantic/*`、`/api/v1/backends/*`

**职责范围**：
- LLM 驱动的智能数据分析（任务解释、查询规划、SQL 生成与执行、结果汇总）
- SSE 流式事件推送
- 分析会话生命周期管理（创建、执行、超时、取消、僵尸回收）
- 语义层管理（指标、维度、同义词）
- 存储后端注册与 Schema/Table/Column 查询

**API 端点清单**：

| 方法 | 路径 | 说明 | 认证要求 |
|------|------|------|----------|
| POST | `/api/v1/analysis` | 提交分析问题（SSE 流） | 是 |
| GET | `/api/v1/analysis/{sessionId}` | 查询分析结果 | 是 |
| GET | `/api/v1/semantic/metrics` | 指标列表 | 是 |
| POST | `/api/v1/semantic/metrics` | 创建指标 | 是 |
| GET | `/api/v1/semantic/dimensions` | 维度列表 | 是 |
| POST | `/api/v1/semantic/dimensions` | 创建维度 | 是 |
| GET | `/api/v1/semantic/synonyms` | 同义词列表 | 是 |
| POST | `/api/v1/semantic/synonyms` | 创建同义词 | 是 |
| GET | `/api/v1/backends` | 存储后端列表 | 是 |
| GET | `/api/v1/backends/{id}/schemas` | Schema 列表 | 是 |
| GET | `/api/v1/backends/{id}/schemas/{schema}/tables` | 表列表 | 是 |
| GET | `/api/v1/backends/{id}/schemas/{schema}/tables/{table}/columns` | 列列表 | 是 |

**子域说明**：

| 子域 | 路由前缀 | 说明 | 未来可拆分性 |
|------|----------|------|-------------|
| 分析核心 | `/api/v1/analysis/*` | LLM 分析、SSE 流、会话管理 | 核心功能，保留在 analysis-service |
| 语义层 | `/api/v1/semantic/*` | 指标/维度/同义词 CRUD | ⚡ 可拆分为独立 semantic-service |
| 存储后端 | `/api/v1/backends/*` | 后端注册、Schema 查询 | ⚡ 可拆分为独立 backend-service |

> **注意**：语义层和存储后端当前作为 analysis-service 的子模块存在，路由前缀已经独立。
> 如果未来模块复杂度增加或需要独立扩缩容，可以拆分为独立服务，只需修改 Gateway 路由即可，前端 API 路径无需变更。

### 3.3 聊天历史域（Chat History Domain）

**当前归属**：auth-service (Java) — **短期方案**

**路由前缀**：`/api/v1/chat/*`

**职责范围**：
- SQL 语句保存、更新、查询
- 聊天消息持久化
- 查询结果保存与历史查询

**API 端点清单**：

| 方法 | 路径 | 说明 | 认证要求 |
|------|------|------|----------|
| POST | `/api/v1/chat/save-sql` | 保存 SQL 语句 | 是 |
| PUT | `/api/v1/chat/update-sql` | 更新 SQL 语句 | 是 |
| POST | `/api/v1/chat/get-sql` | 获取 SQL 语句 | 是 |
| POST | `/api/v1/chat/save-message` | 保存聊天消息 | 是 |
| POST | `/api/v1/chat/save-query-result` | 保存查询结果 | 是 |
| GET | `/api/v1/chat/history` | 获取全部聊天历史 | 是 |
| GET | `/api/v1/chat/query-results` | 获取全部查询结果 | 是 |
| POST | `/api/v1/chat/query-results-between` | 按时间范围查询结果 | 是 |

**⚠️ 迁移计划**：

聊天历史域当前暂存在 auth-service 中，因为其数据存储在 auth-service 的 MySQL 数据库中。
中期计划将其迁移到 analysis-service，配合 MySQL 数据迁移一起完成（参见 architecture-todolist §5.4）。

迁移步骤：
1. Analysis Service 新增 MySQL 连接（复用 auth-service 的 MySQL 实例）
2. 在 Python 端用 SQLAlchemy 重建对应的 Model 和 API 路由
3. 修改 Gateway 路由，将 `/api/v1/chat/*` 指向 analysis-service
4. 从 auth-service 中移除 `ChatHistoryController` 及相关代码
5. API 路径保持不变，前端无需修改

### 3.4 基础设施代理域（Infrastructure Proxy Domain）

**归属**：API Gateway (Nginx)

**路由前缀**：`/api/v1/metadata/*`、`/api/v1/query/*`

**职责范围**：
- Pixels Server 元数据查询代理（Schema、Table、Column、View）
- Pixels Server SQL 查询代理（提交查询、查询状态、查询结果）
- Text-to-SQL 服务代理

**API 端点清单**：

| 方法 | 路径 | 上游目标 | 上游路径 | 说明 |
|------|------|----------|----------|------|
| * | `/api/v1/metadata/*` | Pixels Server | `/api/metadata/*` | 元数据查询 |
| * | `/api/v1/query/*` | Pixels Server | `/api/query/*` | SQL 查询 |
| POST | `/api/v1/query/text-to-sql` | Text2SQL Service | 原路径 | 自然语言转 SQL |

**路径重写规则**：
- `/api/v1/metadata/*` → `/api/metadata/*`（去掉 `v1` 前缀，适配 Pixels Server）
- `/api/v1/query/*` → `/api/query/*`（去掉 `v1` 前缀，适配 Pixels Server）
- `/api/v1/query/text-to-sql` → 直接转发（精确匹配，优先于 `/api/v1/query/*`）

## 4. Gateway 路由规则

### 4.1 路由优先级

Nginx location 匹配按以下优先级排列（从高到低）：

| 优先级 | 路径 | 目标 | 特殊处理 |
|--------|------|------|----------|
| 1 | `= /api/v1/auth/login` | auth-service | Cookie 注入（NJS） |
| 2 | `= /api/v1/auth/refresh` | auth-service | Cookie 注入（NJS） |
| 3 | `= /api/v1/auth/logout` | auth-service | Cookie 清除（NJS） |
| 4 | `= /api/v1/auth/logout-all` | auth-service | Cookie 清除（NJS） |
| 5 | `/api/v1/auth/` | auth-service | 公开端点（无 CSRF） |
| 6 | `/api/v1/chat/` | auth-service | 需认证 + CSRF |
| 7 | `= /api/v1/query/text-to-sql` | Text2SQL Service | 需认证 + CSRF |
| 8 | `/api/v1/query/` | Pixels Server | 需认证 + CSRF，路径重写 |
| 9 | `/api/v1/metadata/` | Pixels Server | 需认证 + CSRF，路径重写 |
| 10 | `/api/v1/analysis` | analysis-service | 需认证 + CSRF，SSE 支持 |
| 11 | `/api/` | analysis-service | 需认证 + CSRF（兜底） |
| 12 | `/` | frontend | 静态资源 |

### 4.2 统一安全策略

所有受保护的 API 端点（除 auth 公开端点外）在 Gateway 层统一执行：

1. **JWT 鉴权透传**：通过 `auth_request /_auth_verify` 调用 auth-service 的 `/api/v1/auth/me` 验证 token
2. **CSRF 双提交验证**：通过 NJS `verifyCsrf` 函数验证 `X-XSRF-TOKEN` 请求头
3. **用户信息注入**：验证通过后，将 `X-Auth-User-Id` 和 `X-Auth-User-Email` 注入到上游请求头
4. **分级限流**：auth 5r/s、analysis 2r/s、general 10r/s

### 4.3 Cookie 管理

Cookie 的写入和清除完全由 Gateway NJS 层处理：

| 端点 | Cookie 操作 | 实现方式 |
|------|-------------|----------|
| `/api/v1/auth/login` | 写入 access_token + refresh_token Cookie | `js_body_filter cookie_handler.injectTokenCookies` |
| `/api/v1/auth/refresh` | 写入新的 token Cookie | `js_body_filter cookie_handler.injectTokenCookies` |
| `/api/v1/auth/logout` | 清除 token Cookie | `js_header_filter cookie_handler.clearTokenCookies` |
| `/api/v1/auth/logout-all` | 清除 token Cookie | `js_header_filter cookie_handler.clearTokenCookies` |

## 5. 跨服务通信规则

### 5.1 通信方式

| 调用方 | 被调用方 | 通信方式 | 说明 |
|--------|----------|----------|------|
| Frontend → Gateway | HTTP/SSE | 所有前端请求通过 Gateway 统一入口 |
| Gateway → auth-service | HTTP | JWT 验证、认证 API 转发 |
| Gateway → analysis-service | HTTP/SSE | 分析 API 转发 |
| Gateway → Pixels Server | HTTP | 元数据/查询代理转发 |
| Gateway → Text2SQL Service | HTTP | Text-to-SQL 代理转发 |

### 5.2 禁止的通信路径

- ❌ 前端直接访问 auth-service（必须经过 Gateway）
- ❌ 前端直接访问 analysis-service（必须经过 Gateway）
- ❌ auth-service 直接调用 analysis-service（服务间无直接依赖）
- ❌ analysis-service 直接调用 auth-service（服务间无直接依赖）

### 5.3 开发环境例外

开发环境下，前端通过 Vite proxy 直连后端服务（绕过 Gateway），这是为了开发便利性。
生产环境必须通过 Gateway 统一入口。

## 6. 新功能归属判断标准

当需要新增 API 端点时，按以下标准判断归属：

```
新功能是否涉及身份认证/会话管理？
  ├── 是 → auth-service（认证域）
  └── 否 → 是否涉及 LLM/数据分析/语义层？
              ├── 是 → analysis-service（分析域）
              └── 否 → 是否是外部服务的代理转发？
                          ├── 是 → Gateway 层（基础设施代理域）
                          └── 否 → 评估是否需要新建服务
```

**具体判断规则**：

| 功能类型 | 归属 | 示例 |
|----------|------|------|
| 用户注册/登录/权限 | auth-service | 密码重置、OAuth 接入 |
| 数据分析/LLM 调用 | analysis-service | 新的分析模式、报告生成 |
| 指标/维度/语义管理 | analysis-service | 指标编辑、维度映射 |
| 存储后端管理 | analysis-service | 新增后端类型、连接管理 |
| 外部数据引擎代理 | Gateway | 新的 Pixels Server 端点 |
| 聊天/历史记录 | auth-service（短期）→ analysis-service（中期） | 聊天历史查询 |

## 7. 未来演进

### 7.1 短期已完成

- [x] Gateway 统一入口，所有 API 路由正确归属
- [x] Query/Metadata/TextToSQL 代理迁移到 Gateway 层
- [x] Chat History 路由修复（Gateway 正确路由到 auth-service）

### 7.2 中期计划

- [ ] 将 ChatHistoryController 从 auth-service 迁移到 analysis-service（配合 MySQL 数据迁移）
- [ ] 从 auth-service 中移除 QueryController、MetadataController、TextToSQLController（已被 Gateway 代理替代）
- [ ] auth-service 收敛为纯粹的身份认证和会话管理服务

### 7.3 长期计划

- [ ] 评估语义层（`/api/v1/semantic/*`）是否需要拆分为独立 semantic-service
- [ ] 评估存储后端（`/api/v1/backends/*`）是否需要拆分为独立 backend-service
- [ ] 引入服务注册与发现机制（如果服务数量增长）
