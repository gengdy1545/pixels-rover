# 后端服务开发指南（跨服务接入契约）

本文档固定 Pixels Rover **后端服务** 的接入契约与边界规范。

- 适用范围：仓库中 `services/*` 下的任何后端服务，以及未来新增的插件式业务服务。
- 设计前提：
  - 产品形态是 **microservice behind API gateway**：每个服务通过 gateway 的统一接入规范对外暴露 HTTP/SSE API，浏览器不直连；
  - 每个服务自带数据边界，短期不横向互调；
  - 内部实现（语言、框架、DI、代码组织、ORM、日志库）由各服务自由决定。
- **本文档只规定"服务如何接进系统"的契约，不规定"服务内部如何实现"**。后者属于各服务团队自己的决策空间，不在本仓库规范范围内。
- 与 [`./gateway.md`](./gateway.md) 互为镜像：`gateway.md §7` 从网关视角写"怎么接入新服务"，本文档从服务视角写"接入要满足什么"。二者需要同步维护。

---

## 1. "插件式后端" 在本项目的确切含义

在本仓库的语境下，"插件式后端"**不是**同进程插件（OSGi / VSCode extension / APISIX 自定义插件那种），而是：

> **每个后端服务通过 gateway 的统一接入规范注册进来，对外只暴露 HTTP/SSE API；浏览器不直连、服务之间短期不横向调用；gateway 用"身份头 + 路由前缀 + CORS / 限流 / 审计"作为唯一接入面。**

基于这个定义：

- **服务内部实现**：自由。`auth-service` 用 Spring Boot，`assistant-service` 用 FastAPI，未来新服务可以用 Go / Rust / Node，只要满足本文档列出的契约。
- **服务接入面**：**必须** 遵守下面 §3–§11 的所有契约，否则服务不是"插件"而是"异物"——能跑，但会污染整体系统的观测、鉴权与运维假设。

---

## 2. 服务拓扑硬约束

所有后端服务必须满足：

1. **浏览器不直连**：`docker-compose.yml` 里只 `expose` 内部端口，**不 `ports`**；所有浏览器流量必须过 gateway。
2. **独占数据域**：每个服务拥有自己的数据库/schema（`pixels_auth` 归 `auth-service`，`pixels_analysis` 归 `assistant-service`，未来新服务走 `pixels_<domain>`）。**禁止跨服务直接读对方的表**。
3. **无横向调用（短期）**：服务之间短期不互相调用。如果出现必须互调的场景，单独评估（候选方案：走内部鉴权的 HTTP 接口；绝不走直连数据库）。
4. **按领域注册路由前缀**：`/api/v1/<domain>*`，以领域命名而不是以实现细节命名（反例：`/api/v1/mysql-stuff/*`、`/api/v1/duckdb/*`）。
5. **依赖关系单向**：服务只能依赖 `auth-service` 提供的身份（经过 gateway 注入的头），不得反向。

---

## 3. 身份契约

### 3.1 必须做

- **只消费** gateway 注入的身份头：
  - `X-Auth-User-Id`
  - `X-Auth-User-Email`
  - `X-Auth-Session-Id`（可选）
- 在每个受保护接口的入口处读取这三个头，并把 `userId` 作为本次请求的主身份参与所有后续判断。

### 3.2 禁止做

- ❌ 自己解 JWT / 读 `access_token` cookie
- ❌ 调 `auth-service` 的 `/api/internal/auth/introspect`（gateway 已做，重复调用会放大 auth-service 压力并破坏缓存策略）
- ❌ 读 `pixels_auth.user` 表或任何 auth-service 的内部表
- ❌ 信任请求 body 或 query 里客户端传来的 `userId` 字段——永远只以 `X-Auth-User-Id` 为准

### 3.3 边界情况：缺失 `X-Auth-User-Id` 的处理

受保护接口收到**没有** `X-Auth-User-Id` 头的请求时，**必须**：

1. **HTTP 状态码返回 500**（不是 401，不是 503）。
2. **响应体 `details.errorCode` 固定为 `GATEWAY_IDENTITY_MISSING`**（使用基础设施前缀 `GATEWAY_*`，不使用业务领域前缀，因为它表达的是接入面故障而非任何领域的业务错误；见 §6.3 命名空间约定）。
3. **服务端日志打 `level=critical`**，字段包含 `requestId` / `method` / `uri` / 入站 `Host` / 真实源 IP。
4. **message 固定为** `"Gateway identity headers missing"`（简短、面向调用方、不暴露诊断细节）。更完整的诊断语境——"请求是否绕过了 gateway"、"gateway 路由是否漏配 `gateway-auth`"、"入站 Host / 真实源 IP"——只写进第 3 条要求的 `level=critical` 结构化日志，不落在响应 message 里（遵守 §6.0 `message` 边界）。

**为什么是 500 而不是 401 / 503**：

- **不是 401**：到达业务服务的请求一定已通过网关的 AuthN；服务自己不做 AuthN（见 §3.2）。返 401 会让调用方误以为"重新登录就能解决"，掩盖真正的配置故障。
- **不是 503**：503 的语义是"某个可恢复的下游依赖瞬时不可用，稍后重试可能成功"。缺身份头不是"瞬时"而是"配置错误"——路由漏配 `gateway-auth`、服务被直连（绕过网关）、apisix.yaml 回滚后遗漏——这些事情不会因为"稍后重试"就自愈。
- **是 500**：明确告诉监控系统"服务端遇到了不应发生的情况"，触发 critical 告警而非普通错误计数；同时在不暴露内部细节的前提下给调用方一个不可误读的信号。

**正常情况下，服务永远不会收到无身份头的受保护请求**——出现即事故，不是业务。

### 3.4 特殊服务：`auth-service` 的接入定位

`auth-service` 在系统中有双重身份：

1. **AuthN 真源**：持有 JWT 签名/验签密钥、持有 session 表、对外提供 `introspect`。
2. **普通业务服务**：对外提供 `/api/v1/auth/me`、`/api/v1/auth/logout`、`/api/v1/auth/sessions*` 等**用户面** REST 接口，与 `assistant-service` 的业务接口并无本质差异。

**硬规则**：把这两种身份在**代码层彻底切开**，不允许混在同一条 `SecurityFilterChain`、同一条 URL 规则、同一套身份识别逻辑里。

| 接口类型 | URI 前缀 | 身份来源 | 是否允许持有/解码 JWT |
|---|---|---|---|
| **内部接口**（introspect、JWKS 等） | `/api/internal/auth/*` | 由服务自己在 §8.6 `InternalAuthFilter` 中校验 `X-Internal-Auth` secret | ✅ **允许**（只在这一个区域） |
| **用户面业务接口** | `/api/v1/auth/*`（除 `login` / `register` / `captcha` / `refresh` 四个公开路由外） | **只读 `X-Auth-User-Id` / `X-Auth-User-Email` / `X-Auth-Session-Id`**，与 §3.1 完全一致 | ❌ **禁止** |
| **公开 POST**（`login` / `register` / `captcha`） | `/api/v1/auth/*`（具体四条） | 不需要身份 | ❌ **禁止** |
| **`refresh`**（特殊） | `/api/v1/auth/refresh` | 从 `refresh_token` cookie 读（这是业务逻辑，不是身份识别） | ❌ **禁止** 在 Security 层解 JWT；只允许在 controller 内把 cookie 值当字符串 token 交给 `SysLoginService` 做轮换逻辑 |

**为什么要这么拆**：

- auth-service 如果在用户面也自己解 JWT，相当于同一个请求在 gateway 和 auth-service 处被验两次；**两处验签逻辑一旦漂移**（例如 gateway 的 introspect 结果被 cache 命中而 auth-service 直接解 token 拿到更新的 claims），就会出现"同一用户在同一请求里被看作两个身份"这种极难排查的故障。
- 更深一层：auth-service 的用户面接口**本质上和 `assistant-service` 没有区别**——只是恰好把 session 表放在 `pixels_auth` 里。把它按普通业务服务看待，`backend.md §3.1/§3.2` 所有条款都直接适用，规范就不需要为 auth-service 单独开口子。
- JWT 解码能力是 **auth-service 的内部能力**，这个能力只在 `/api/internal/*` 和内部 service 层（签发、轮换、撤销）使用；"能不能解 JWT"和"接口对外是什么语义"是两件事，按 URI 空间彻底切开。

**边界精确定义：是 `SecurityFilterChain`，不是代码调用栈**。

上面的"禁止持有/解码 JWT"**不是**在说 `SysLoginService.refreshToken()` 或 `JwtTokenProvider` 这些内部 service/provider 层不能碰 JWT——它们恰恰就是为碰 JWT 存在的。真正的边界是：

- ✅ **允许**：service / mapper / provider 层内部把 cookie 取出来的字符串当作 token 交给 `JwtTokenProvider` 做验签、轮换、session 活性判断。这是领域逻辑。
- ❌ **禁止**：把 `JwtAuthenticationFilter` 挂到 `/api/v1/auth/**` 的 `SecurityFilterChain`。
- ❌ **禁止**：在用户面 controller 里走 `SecurityContextHolder.getContext().getAuthentication()` 拿身份。
- ❌ **禁止**：在用户面 controller 里调 `jwtTokenProvider.getUsernameFromToken(cookieValue)` 来"识别当前请求的用户身份"——这个判断应该只来自 `@RequestHeader("X-Auth-User-Id")`。

**判定口诀**：如果一个调用栈起点是"web 层（filter 或 controller）要知道当前请求是谁"，就**必须**只读 `X-Auth-*` 头；如果起点是"领域逻辑要处理某个 token 字符串"（比如 refresh 轮换、logout 撤销），那 JWT 解码是这个领域本来就要做的事，和身份识别无关。两件事被新人混为一谈是历史上最常见的漂移源。

**落地动作**（见 `.notes/todolist.md`）：

- 拆分 `SecurityFilterChain` 为两条：`internalApiChain`（`/api/internal/**`，用 `InternalAuthFilter`）、`publicAndUserChain`（`/api/v1/auth/**` 及 `/health`，无 JWT filter）。
- 删 `JwtAuthenticationFilter` 在用户面链路上的挂载；`/me` / `/logout` / `/logout-all` / `/sessions*` 从 `SecurityContextHolder` 换到 `@RequestHeader("X-Auth-User-Id")`。
- 用户面 controller 参数**必须**用 `@RequestHeader(name="X-Auth-User-Id", required=true)`（**不是** `required=false`）。头缺失时 Spring 抛 `MissingRequestHeaderException`，由 §6.5 的 `GlobalExceptionHandler` 兜成 `500 + details.errorCode="GATEWAY_IDENTITY_MISSING"`（和 §3.3 完全一致）。这样"接入面事故"在代码层就不会被某个 controller 悄悄忍掉。
- `resolveCurrentSessionId` 这类辅助函数不再从 cookie 解 JWT，直接读 `X-Auth-Session-Id`。
- **`/api/v1/auth/refresh` 的硬边界**：controller 层从 `refresh_token` cookie 取字符串、交给 `SysLoginService` 做轮换与 session 活性判断；**不经过** `JwtAuthenticationFilter`、**不用** `SecurityContextHolder`、**不在** controller 里调 `jwtTokenProvider.getUsernameFromToken(...)` 作为"识别当前请求者"的依据（该调用只应作为"这个 token 字符串在业务上是否合法"的领域判断出现在 service 层）。违反这条即触犯了本节开头"web 层识别身份 vs 领域逻辑处理 token"的口诀。

---

## 4. 资源授权与数据边界

### 4.1 资源级授权由服务承担

`gateway` 只做"是否登录"级别的粗粒度授权。**任何"这个资源是不是属于当前用户"的判断都必须在服务内完成**：

- 查询接口：在 SQL/ORM 里加 `WHERE owner_user_id = :userId`，或在 service 层显式判断。
- 修改/删除接口：必须先校验资源归属再执行操作。
- 列表接口：必须过滤到当前用户可见的资源，**不能把"未授权"作为前端的过滤职责**。

### 4.2 对"非本人资源"一律返回 404

对于当前用户无权访问的资源，返回 **404 Not Found** 而不是 403 Forbidden。

- 理由：403 会让攻击者通过"存在即返回 403 / 不存在即返回 404"的差异枚举他人资源 ID，直接暴露资源空间。
- 统一 404：资源访问失败时，调用方无法区分"不存在"和"存在但无权"。

### 4.3 数据边界

- 每个服务只读写自己持有的数据库 schema。
- 跨服务数据需求只能通过 HTTP API 获取（且当前阶段避免引入这种依赖；实在需要时单独评估）。
- 严禁通过共享数据库或跨库 JOIN 来"方便地"拿到其他服务的数据。

---

## 5. Request-Id 契约

**责任分割**（与 [`./gateway.md §8.1`](./gateway.md) 对齐，避免"谁负责写响应头"这类漂移）：

| 层 | 行为 |
|---|---|
| Gateway | 入口**必须保证** `X-Request-Id` 存在（缺失时生成 128-bit 随机值），同时注入**请求头**与**响应头**。 |
| 业务服务 | 仅**消费并透传**：从入站请求头读 `X-Request-Id`，贯穿所有日志、下游调用、响应信封 `requestId` 字段；**不主动写 `X-Request-Id` 响应头**（由 gateway 统一下发，避免与 gateway 值漂移）。 |

- **必须透传** `X-Request-Id` 到所有下游调用、异步任务、日志、错误响应。
- **必须**在结构化日志的每条记录里携带 `requestId`。
- **必须**在入站 filter / middleware 的最外层初始化"请求级 `requestId` 上下文"（如 Spring 的 `RequestIdContext` ThreadLocal、FastAPI 的 `ContextVar`），让响应信封（`ApiResponse.requestId` / `api_error(...)["requestId"]`）与日志格式化器都能从同一上下文读。**缺上下文即 bug**——响应信封 `requestId` 字段不允许为 `null`/缺省。
- **缺失时不要回填响应头**——gateway 保证入口一定有该头，缺失应视为 gateway 配置错误（apisix.yaml 漏注入、或请求未经 gateway 直达）。
- **缺失时的处理规则**（避免日志完全失声）：
  1. 在日志里按一次告警记录 `request_id_missing=true` + 触发的 route；
  2. 在**日志与错误响应 body** 的 `requestId` 字段用本地 fallback 值 `missing-<8-char-rand>`，便于单次事故日志仍可聚合；
  3. **不把 fallback 写回响应头**——避免污染下游 request-id 链路。
- 错误响应 body 里必须包含 `requestId` 字段，方便用户反馈时定位链路。

---

## 6. 响应模型（成功 + 失败统一）

### 6.0 统一响应信封

**所有** HTTP 响应（成功与失败）共用同一个顶层信封：

```jsonc
{
  "code":      <int>,       // 必填；数值上等于 HTTP 状态码
  "message":   "<string>",  // 必填；给人读的简短描述
  "requestId": "<string>",  // 必填；贯穿链路的 request id（见 §5）
  "data":      <T>,         // 成功时出现；失败时禁止出现
  "details":   {...}        // 失败时出现；成功时禁止出现
}
```

**字段约束**：

- **`code`（顶层）必须等于 HTTP 状态码**（`200` / `400` / `404` / `500` / ...）。禁止使用 `40100` / `40102` 这类 5 位"业务码"——业务细分是 `details.errorCode` 的职责，顶层 `code` 只表达协议语义。
- **`message`**：面向终端用户或调用方的人类可读短语（成功场景可为 `"OK"` 或省略的简短字符串；失败场景应描述"出了什么问题"）。无论成功还是失败，**禁止**写入堆栈、SQL 文本、内部路径、内部类/函数名、真实主机名/IP、token 片段或任何可能在面向外网/前端日志里成为信息泄漏面的内容。面向开发者的调试信息一律写结构化日志并用 `requestId` 关联，不经由 `message` 带出。
- **`requestId`**：见 §5；所有响应必填。
- **`data` 与 `details` 互斥**：同一响应只会出现其中之一。`200 OK` 带 `data`，非 2xx 带 `details`（`details` 本身仍然可选，某些简单错误可以不带）。
- **不允许出现 `apiVersion` 字段**：API 版本由 URL 前缀 `/api/v1/` 唯一承载，body 里重复只会导致"URL 说 v1、body 说 v2"这类漂移事故。

### 6.1 成功响应 schema

```jsonc
{
  "code": 200,
  "message": "success",
  "data": { /* 业务载荷 */ },
  "requestId": "a1b2c3d4..."
}
```

- `code` 统一为 HTTP 状态码（`200` / `201` / `204`）。
- `message` 对成功响应通常是 `"success"` 或简短动作描述（`"Login success"`），不要堆业务信息。
- `data` 的形状由各接口的 OpenAPI 定义；**空响应用 `"data": null`**（或干脆省略 `data` 字段），不要返回 `{}`。
- 禁止把错误字段（`errorCode` / `hint`）偷偷塞进成功响应。

### 6.2 HTTP 状态码语义（统一）

| 状态码 | 语义 | 典型场景 |
|---|---|---|
| `200` / `201` / `204` | 成功 | 标准 REST |
| `400` | 请求参数校验失败 | JSON schema 错、字段类型错 |
| `404` | 资源不存在或非本人拥有 | 见 §4.2 |
| `409` | 冲突 | 并发修改、重复创建 |
| `422` | 业务规则拒绝 | 超配额、状态不允许 |
| `500` | 服务端未知错误 / 接入面故障 | 未捕获异常、缺 `X-Auth-*` 头（见 §3.3） |
| `503` | 瞬时依赖不可用 | DB 不可达、LLM 超时、introspect 超时 |

**禁用 401 / 403**：认证失败和粗粒度授权失败由 gateway 统一返回；到达业务服务的请求一定是已认证的。服务端任何地方出现 401/403 返回都是 bug。

**禁用数字业务码**：顶层 `code` **只允许**是合法的 HTTP 状态码（`200` / `400` / `404` / `500` / ...）。历史代码里出现的 `40000` / `40100` / `40102` 这类 5 位数字"业务码"**全部废弃**——业务细分由 `details.errorCode`（字符串）承担，数字承担协议语义。**不允许**保留"数字→字符串名"的反查表（例如 `ErrorCodeName.fromCode`、`resolve_error_code_name`）作为过渡，因为一旦存在，上层代码就会继续填数字码，漂移源永远关不掉。

**框架默认行为的调整**：

- FastAPI 默认对请求体校验失败返回 `422`；本项目语义下属于"请求格式错误"，**必须调整为 `400`**（通过自定义 `RequestValidationError` 处理器实现）。
- Spring Boot `@Valid` 默认返回 `400`，与本项目一致；无需调整。
- 以"业务规则拒绝"（超配额、状态机非法跃迁）为语义的错误才用 `422`。

### 6.3 错误响应 schema

```jsonc
{
  "code": 422,
  "message": "Quota exceeded",
  "requestId": "a1b2c3d4...",
  "details": {
    "errorCode": "ANALYSIS_QUOTA_EXCEEDED",
    "hint": "optional machine-readable context"
  }
}
```

- `code` 等于 HTTP 状态码（见 §6.2）。
- `details` 是失败响应专属的**业务细分载体**；成功响应禁止出现此字段。
- **`details.errorCode` 强制规范**（**所有失败响应必须带上**，无论 HTTP 状态；§3.3 的 `GATEWAY_IDENTITY_MISSING` 与 §8.6 的 `INTERNAL_AUTH_FAILED` 作为 500 错误同样必填。仅"完全未知、无法归类的未捕获异常"在到达 §6.5 的兜底 handler 时允许省略 `errorCode`，此时必须伴随 `level=error` 的日志条目）：
  - 格式：`SCREAMING_SNAKE_CASE`。
  - **命名空间一分为二、互不重叠**：
    - **业务领域前缀**（`<DOMAIN>_<REASON>`）——归属某个业务领域的错误：
      - `auth-service` → `AUTH_*`（例：`AUTH_PASSWORD_TOO_WEAK`、`AUTH_CAPTCHA_INVALID`）
      - `assistant-service` 的 analysis 领域 → `ANALYSIS_*`（例：`ANALYSIS_QUOTA_EXCEEDED`）
      - `assistant-service` 的 conversation 领域 → `CONVERSATION_*`
      - 新服务按领域命名：`NOTIFICATION_*` 等
    - **基础设施前缀** `GATEWAY_*` / `INTERNAL_*`——不属于任何业务领域，表达接入面或跨服务内部通信基础设施故障。已保留的固定串：
      - `GATEWAY_IDENTITY_MISSING`（业务服务收到无身份头请求，见 §3.3）
      - `GATEWAY_AUTH_REQUIRED`（gateway 判定未登录，见 gateway.md §5.1）
      - `GATEWAY_CSRF_INVALID`（gateway 判定 CSRF 校验失败，见 gateway.md §5.1）
      - `GATEWAY_INTROSPECT_UNAVAILABLE`（gateway 调 introspect 失败，见 gateway.md §5.1）
      - `INTERNAL_AUTH_FAILED`（internal 接口 secret 校验失败，见 §8.6）
  - **两类前缀空间严格互斥**：业务领域前缀永远是**领域名**（`AUTH` / `ANALYSIS` / `CONVERSATION` / `NOTIFICATION` ...），基础设施前缀永远是**基础设施角色名**（`GATEWAY` / `INTERNAL` ...）。未来新增业务领域或基础设施组件时，前缀必须落在对应命名空间，不允许跨类混用。
  - 枚举值应在服务的 OpenAPI `details.errorCode` schema 的 `enum` 中列出，作为契约的一部分（见 §9）。
- **`details.hint`** 与其他业务字段（如 `details.field`、`details.retryAfterSec`）：各服务可按需扩展，但不得违反 §6.4 "不暴露内部细节"。

### 6.4 错误信息边界

- ❌ **不要** 把异常堆栈、SQL 语句、内部组件名暴露给客户端。
- ❌ **不要** 在 4xx 错误里透露"数据库连不上"这种内部信息（应该 `503` + 通用描述）。
- ❌ **不要** 在响应信封里新增顶层业务字段（`apiVersion` / `traceId` / 自定义 meta）——任何扩展走 `details.*`。
- ✅ 内部细节只写进服务端日志（绑定 `requestId`），便于排障。

### 6.5 Framework 级兜底：global exception handler 的责任

各服务**必须**在 framework 层注册一个全局异常处理器，保证**任何出站响应**都走 §6.0 定义的统一信封——包括框架默认的错误响应（FastAPI 的 `{"detail": "..."}`、Spring Boot 的 `{"timestamp":..., "status":..., "error":...}`、未捕获异常的 HTML 错误页等）。直接暴露框架默认错误响应视为契约违反。

**落地要求**：

- **FastAPI**：注册 `@app.exception_handler(Exception)` + `@app.exception_handler(HTTPException)` + `@app.exception_handler(RequestValidationError)` 三个最外层 handler，统一走 `api_error(...)`。其中 `RequestValidationError` 强制返 `400`（见 §6.2），不使用框架默认的 `422`。
- **Spring Boot**：`@RestControllerAdvice` 的 `GlobalExceptionHandler` 至少覆盖：`MissingRequestHeaderException`（特别是 `X-Auth-User-Id` 缺失 → `500 + GATEWAY_IDENTITY_MISSING`，见 §3.3）、`MethodArgumentNotValidException` → `400`、`HttpMessageNotReadableException` → `400`、`Exception.class` 兜底 → `500`。全部走 `ApiResponse.error(...)`。
- **未捕获异常的 `message`**：必须是面向调用方的通用短语（如 `"Internal server error"`），**禁止**把异常 class 名、堆栈、原始 SQL、内部组件名写入 `message`——这些只写结构化日志（§6.4）。

**为什么单独列成一条**：没有这层兜底，新同学写某个 controller 忘了 try-catch，一次 NPE 就会让外部拿到框架默认的响应结构，前端按信封解析直接崩掉——这是历史上最常见的"本地测没事、上线一炸一片"的源头。

---

## 7. 健康检查契约

### 7.1 `/health` —— 服务自身健康

- 必须暴露。
- **只判断"自己能响应请求"**：返回 200 + JSON，例如 `{"status":"ok"}`。
- **禁止**在 `/health` 内级联探测数据库、缓存、LLM、其他服务。
- **用途**：Docker healthcheck、K8s livenessProbe、compose `depends_on: condition: service_healthy`。

### 7.2 `/ready` —— 可选的就绪度

- 需要"对外可服务"语义时才暴露。
- 可以探 DB / 依赖缓存 / LLM 可达性，聚合后返回。
- **禁止**作为容器自身重启判据；只用于流量调度（LB 摘流、K8s readinessProbe）。

### 7.3 失败响应

- `/health` 失败返回 **503**，响应体沿用 §6.2 的错误 schema。

---

## 8. API 设计约定

### 8.1 REST 风格

- 资源名用名词复数（`/conversations`、`/analyses`），动作放方法（`POST /conversations`，`DELETE /conversations/{id}`）。
- 非 REST 性质的操作可以在资源下挂子资源或显式动作（`POST /analyses/{id}:cancel` 这种显式动作风格只在真正必要时用）。
- 幂等约束：`GET` / `PUT` / `DELETE` 必须幂等；`POST` 不要求幂等但必须幂等时应支持 `Idempotency-Key` 头。

### 8.2 URI 命名

- 领域前缀固定：`/api/v1/<domain>*`。
- 资源 ID 用 URL-safe、稳定的标识符（UUID / ULID 优先于自增整数）。
- **不在** URI 中暴露实现细节（表名、引擎名、数据库名）。

### 8.3 分页、过滤、排序

- 分页：`?page={n}&size={n}` 或 cursor 风格（`?cursor=...&limit=...`），每个服务内部统一一种。
- 排序：`?sort=field:asc` / `sort=field:desc`。
- 过滤：显式字段（`?status=active`），不做"魔法字段"。

### 8.4 时间戳 / 字符串规范

- 时间：统一 **ISO 8601 UTC**（`2026-04-21T08:30:00Z`）。
- 字段命名：JSON body / query 统一 **camelCase**（前端直接映射）。
- 数据库里可以用 snake_case，但对外 API 必须 camelCase。
- 枚举：固定小写串（`"pending"`、`"running"`、`"done"`），不用整数或首字母大写。

### 8.5 API 版本

- 所有业务路由以 `/api/v1/...` 开头。
- **Breaking change** 必须通过新版本前缀（`/api/v2/...`），不得原地改 schema。
- 新增字段（前端可忽略）不构成 breaking change，可以原地加。

### 8.6 Internal 接口（只允许网关内部调用）

服务若需要暴露"只给 gateway 或其他可信内部调用者访问"的接口（例如 auth-service 的 `introspect`、gateway 未来的 `invalidate_session`），必须满足：

- **URI 前缀固定为** `/api/internal/*`。
- **必须校验** `X-Internal-Auth: ${INTERNAL_*_SECRET}` 请求头；不同 internal 接口可使用不同 secret（如 `INTERNAL_INTROSPECTION_SECRET`），不共享同一把。
- 该校验**不是** gateway 层的 `gateway-auth`，而是由**服务自己**在应用层实现——因为 gateway 是这类接口的上游调用方，它自己不会拦自己。
- `apisix.yaml` **禁止** 把任何 `/api/internal/*` 前缀对外 route；gateway 内部调用走 upstream 直连。
- **校验失败统一返回 `500` + `details.errorCode = "INTERNAL_AUTH_FAILED"`**，**不要回 401/403**。
  - 为什么不是 503：503 语义是"依赖瞬时不可用"，secret 错不会随重试变对。
  - 为什么不是 401/403：会向外部探测者泄露"路径存在且要求内部凭据"的信息，给攻击者一个可以继续试的信号。
  - 500 的作用：让探测者观察到的响应与"路径根本不存在时被 apisix.yaml 拦下"尽量不可区分（两者对外都是 5xx / 404 级别的非业务响应），同时仍触发服务端监控告警。
- 日志里记录 `internal_call=true` 与调用方身份（从 secret 或 mTLS 证书解析），方便审计。

---

## 9. OpenAPI 输出要求

- 每个服务必须稳定输出 OpenAPI 描述。
- **统一路径**：**`/openapi.json`**（不是 `/v3/api-docs`，不是 `/docs`）。所有服务必须一致。
  - FastAPI 默认即为 `/openapi.json`，无需配置。
  - Spring Boot 需要加 `springdoc.api-docs.path=/openapi.json`（同时可保留 `/swagger-ui.html` 作为调试页）。
  - 其他语言/框架均需对齐到该路径。
- 该描述是前端 `frontend/src/shared/types` 的**唯一契约来源**——短期可以由前端手写镜像，长期建议走 OpenAPI 代码生成（参见 `.notes/todolist.md §9`）。
- 每次 API 变动必须同步更新 OpenAPI，不能让文档和实现漂移。
- `details.errorCode` 的枚举值（见 §6.2）应在 OpenAPI 中显式列出。

---

## 10. 观测字段与指标

### 10.1 结构化日志必备字段

每条入站/出站日志至少包含：

| 字段 | 语义 |
|---|---|
| `requestId` | 见 §5 |
| `userId` | `X-Auth-User-Id`（未认证路由为空） |
| `sessionId` | `X-Auth-Session-Id`（可空） |
| `method` / `uri` / `status` | 基础 HTTP 信息 |
| `elapsedMs` | 处理耗时 |
| `service` | 服务名（`auth-service` / `assistant-service` / ...） |

### 10.2 Prometheus 指标维度

每个服务至少暴露以下计数/直方图：

- 请求总数（按 route / status 拆分）
- 错误数（5xx、4xx）
- 延迟直方图（按 route）
- 业务健康指标（由服务决定）

---

## 11. 由 gateway 承担、服务侧**不再处理**的事

下列职责已由 gateway 统一承担，服务侧**必须关闭或不实现**：

- **CORS**：唯一在 gateway `cors` 插件处理（见 `gateway.md §6.4`）。
- **认证（AuthN）**：gateway 调 introspect 完成。
- **CSRF**：gateway `gateway-auth` 插件完成。
- **粗粒度授权**（是否登录、是否 admin）：gateway 路由级配置。
- **Request-Id 生成**：gateway 统一补齐，服务只透传。
- **限流 / 熔断**：gateway 通用策略覆盖所有业务服务。

服务侧如果发现自己在处理上面任何一项，先停下来检查是不是真的必要——几乎总不应该。

---

## 12. 新增后端服务接入 Checklist

当新增一个业务服务（例如 `notification-service`）时，严格按下列顺序：

### 12.1 服务侧准备

- [ ] 选定领域前缀 `/api/v1/<domain>*`
- [ ] 规划独占数据库 schema（`pixels_<domain>`）
- [ ] 实现 `/health`（只探自己）
- [ ] 从 `X-Auth-*` 头读身份，禁止自己做 AuthN
- [ ] 统一错误响应 schema（见 §6.2）
- [ ] 透传 `X-Request-Id`
- [ ] 输出 OpenAPI
- [ ] 结构化日志包含 §10.1 必备字段
- [ ] 关闭服务侧 CORS

### 12.2 接入 gateway

参见 [`./gateway.md §7`](./gateway.md)：
- [ ] 在 `apisix.yaml` 声明 upstream
- [ ] 声明 route 与 `gateway-auth` 插件
- [ ] 配置 `limit-count` / timeout
- [ ] SSE / 长连接路由单独声明超时

### 12.3 基础设施

- [ ] `docker-compose.yml` 只 `expose` 内部端口
- [ ] 声明独立数据库 schema 的初始化脚本
- [ ] 不引入对 `auth-service` / `assistant-service` 数据库的直接依赖

### 12.4 文档

- [ ] 在 `.notes/engineering-design.md` 补记服务拥有关系、数据边界、对外 API 面
- [ ] 不需要为内部实现写项目级文档——那是服务团队内部的事

---

## 13. 显式约束：什么**不要做**

为了保证"插件式"名副其实，下列事项在可预见未来**都不做**，出现在 PR 里需要 justify：

- ❌ **不自己解 JWT / 读 access_token cookie**
- ❌ **不自己调 `introspect`**
- ❌ **不读其他服务的数据库表 / 不跨库 JOIN**
- ❌ **不自己开 CORS**
- ❌ **不返回 401 / 403**（AuthN / 粗粒度 AuthZ 由 gateway 负责）
- ❌ **不在 `/health` 里级联探测外部依赖**
- ❌ **不在错误响应里暴露堆栈、SQL、内部组件名**
- ❌ **不信任客户端传来的 `userId`**
- ❌ **不在 URI 中暴露实现细节**（表名、引擎名）
- ❌ **不对外暴露服务端口**（只能 `expose`，不能 `ports`）
- ❌ **不对外 route `/api/internal/*`**（该前缀专供 gateway 等可信内部调用者，见 §8.6）
- ❌ **不对 internal 接口返回 401/403/503**（`X-Internal-Auth` 校验失败统一 `500` + `details.errorCode="INTERNAL_AUTH_FAILED"`，见 §8.6）

---

## 14. **不** 在本文档规定的内容（明确划清边界）

以下属于"服务内部实现"，各服务团队自由决定，**本仓库规范不涉及**：

- 语言选型（Java / Python / Go / Node / Rust / ...）
- 框架选型（Spring / FastAPI / Axum / Express / Fastify / ...）
- 数据库驱动、ORM、连接池参数
- 依赖注入方式、代码组织
- 业务模块拆分粒度
- 内部异步/并发模型
- 测试框架与测试策略
- 日志 / trace 库
- 构建工具、镜像分层、CI pipeline 细节
- 具体业务功能的实现方式（planner / backend adapter / 业务规则引擎等）

也就是说：**服务对外是一个能被本仓库接入的"盒子"，盒子里长什么样是服务团队的事。**

---

## 15. 参考

- 网关接入规范：[`./gateway.md`](./gateway.md)
- 前端开发纪律：[`./frontend.md`](./frontend.md)
- 设计决策沿革：[`../../.notes/engineering-design.md`](../../.notes/engineering-design.md)（冲突时以本文档为准）
- 当前可执行 backlog：[`../../.notes/todolist.md`](../../.notes/todolist.md)
