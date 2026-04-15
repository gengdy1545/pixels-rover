# Pixels Rover 统一鉴权与身份传递规范

## 1. 目标

本文档定义 Pixels Rover 当前阶段的统一鉴权与身份传递规范，并明确：

- 当前已经落地的最小可用闭环
- 距离工业生产可用方案仍存在的差距
- 前后端与多后端之间的身份传递规则
- 各接口的认证边界

## 2. 为什么先落最小闭环

“最小闭环”不是最终目标，而是工程推进中的第一阶段。

先落最小闭环的原因：

- 先验证 Java 签发 JWT、前端透传 JWT、Python 校验 JWT 这条主链路是否成立
- 先暴露跨语言、跨服务之间的协议问题，避免直接上复杂方案后排障困难
- 先统一基础身份语义，再逐步叠加生产级能力，例如密钥轮换、撤销机制、网关、审计和多端登录策略

但这不代表当前方案已经达到工业生产直接可用标准。

## 3. 当前已落地内容

### 3.1 签发方与校验方

- Java `auth-service` 是唯一 JWT 签发方
- Java `auth-service` 自身可校验 JWT
- Python `analysis-service` 已接入 JWT 校验逻辑

### 3.2 统一请求头

- 所有受保护接口统一使用：

```http
Authorization: Bearer <access_token>
```

- 所有普通 JSON 请求与分析提交流式请求都应携带：

```http
X-Request-Id: <uuid-or-client-generated-id>
```

### 3.3 当前 JWT 约定

当前 token 至少包含以下字段：

- `alg`: 当前代码已支持 `HS256` 与 `RS256`
- `kid`: 当前代码已支持写入和校验，迁移期推荐始终携带
- `iss`: `pixels-rover-auth-service`
- `sub`: 用户邮箱
- `uid`: 用户 ID
- `sid`: 会话 ID
- `type`: `access` 或 `refresh`
- `jti`: refresh token 唯一 ID（refresh token 必带）
- `iat`: 签发时间
- `exp`: 过期时间

### 3.4 当前前端行为

- 前端通过 `withCredentials: true` 自动携带 HttpOnly Cookie 发起受保护请求
- `access_token` 和 `refresh_token` 存储在 HttpOnly Cookie 中，前端 JS 不可直接读取
- 前端通过非 HttpOnly 的 `logged_in` Cookie 检测登录状态（`cookie.ts` → `isLoggedInCookie()`）
- 前端从非 HttpOnly 的 `XSRF-TOKEN` Cookie 读取 CSRF Token，并通过 `X-XSRF-TOKEN` header 发送（`client.ts` 请求拦截器）
- 遇到 `401` 时会尝试调用 refresh 端点（依赖 HttpOnly Cookie 自动发送 `refresh_token`）
- 刷新成功后网关 NJS 自动注入新的 Cookie，前端无需手动管理 token
- 刷新失败则跳转登录页（网关会清除相关 Cookie）

### 3.5 当前会话与 token 生命周期行为

- 登录成功时，Java `auth-service` 会创建一条设备级会话记录，并为该会话签发带有 `sid` 的 `accessToken` / `refreshToken`
- 每次调用 `POST /api/v1/auth/refresh` 都会执行 refresh token 轮换，返回新的 `accessToken` 与新的 `refreshToken`
- 服务端只保存 refresh token 哈希，不保存明文 refresh token
- 如果旧 refresh token 在轮换后再次被使用，系统会将整个会话标记为撤销
- Java `auth-service` 会在鉴权过滤器中校验会话是否已撤销，从而让同一会话下的 access token 失效
- 当前已提供 `GET /api/v1/auth/sessions`、`POST /api/v1/auth/logout`、`POST /api/v1/auth/logout-all`、`DELETE /api/v1/auth/sessions/{sessionId}` 用于会话管理

### 3.6 当前 Python 服务行为

- Python 分析服务校验 Java 签发的 Bearer token
- Python 不再信任前端传入的 `user_id`
- Python 从 token 中提取 `uid` 作为真实用户身份

### 3.7 当前链路追踪与错误契约

- Java 与 Python 都已支持 `X-Request-Id`
- 前端现在会为普通 API 请求和分析 SSE 提交请求主动生成并透传 `X-Request-Id`
- Java 成功响应已统一为 `code/message/data/requestId`
- Java 与 Python 的核心错误响应已统一为 `code/message/errorCode/requestId`
- Python 常规成功响应与 `HTTPException` 错误响应已开始统一为 `code/message/data?/requestId`
- SSE 流式响应仍保留事件流格式，不适用普通 JSON 包装
- 完整的 API 契约规范详见 [api-contract-spec.md](/mnt/disk2/pixels-rover/docs/api-contract-spec.md:1)

当前已统一的核心 `errorCode` 包括：

- `INVALID_ARGUMENT`
- `AUTHENTICATION_REQUIRED`
- `INVALID_CREDENTIALS`
- `INVALID_TOKEN`
- `INVALID_TOKEN_TYPE`
- `ACCESS_DENIED`
- `RESOURCE_NOT_FOUND`
- `RESOURCE_CONFLICT`
- `INTERNAL_ERROR`

### 3.8 当前配置对齐要求

Java `auth-service` 与 Python `analysis-service` 当前必须保持这些配置一致：

- `jwt.issuer`
- 迁移期使用 `HS256` 时：`jwt.secret`
- 迁移期或目标态使用 `RS256` 时：`jwt.algorithm`、`jwt.active-kid`、公钥配置

当前代码已经支持：

- Java：`HS256` / `RS256` 双模式签发与校验
- Python：`HS256` / `RS256` 双模式校验
- `kid` 头解析与基于 `kid` 的 RSA 公钥选择
- 本地统一启动脚本默认使用开发用 `RS256 + kid`

但当前默认配置仍是：

- `HS256`
- 单对称密钥
- 未正式启用生产级密钥轮换

如果任一项不一致，会直接导致 Python 无法校验 Java 签发的 token。

## 4. 当前接口认证边界

### 4.4 统一鉴权失败语义

当前核心鉴权错误语义约定如下：

- 缺少 Bearer token：HTTP `401`，`code=40100`，`errorCode=AUTHENTICATION_REQUIRED`
- token 无效或过期：HTTP `401`，`code=40102`，`errorCode=INVALID_TOKEN`
- token 类型错误：HTTP `401`，`code=40103`，`errorCode=INVALID_TOKEN_TYPE`
- 无权访问资源：HTTP `403`，`code=40300`，`errorCode=ACCESS_DENIED`
- 资源不存在或对当前用户不可见：HTTP `404`，`code=40400`，`errorCode=RESOURCE_NOT_FOUND`

### 4.1 允许匿名访问

Java `auth-service`：

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register`
- `GET /api/v1/auth/captcha`
- `POST /api/v1/auth/refresh`

### 4.2 必须登录后访问

Java `auth-service`：

- `GET /api/v1/auth/user-info`
- `GET /api/v1/auth/sessions`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/logout-all`
- `DELETE /api/v1/auth/sessions/{sessionId}`
- 其他未放开的业务接口

Python `analysis-service`：

- `POST /api/v1/analysis`
- `GET /api/v1/analysis/{session_id}`
- `GET /api/v1/backends`
- `GET /api/v1/backends/{backend_id}/schemas`
- `GET /api/v1/backends/{backend_id}/schemas/{schema}/tables`
- `GET /api/v1/backends/{backend_id}/schemas/{schema}/tables/{table}/columns`
- `GET /api/v1/semantic/metrics`
- `POST /api/v1/semantic/metrics`
- `GET /api/v1/semantic/dimensions`
- `POST /api/v1/semantic/dimensions`
- `GET /api/v1/semantic/synonyms`
- `POST /api/v1/semantic/synonyms`

### 4.3 当前仍未细分的边界

当前所有 Python 分析相关接口一律要求登录，但还没有进一步做到：

- 普通用户与管理员权限区分
- 只读接口与写接口的权限分级
- 基于组织、数据域或租户的访问隔离

## 5. 当前方案距离工业生产可用的差距

下面这些能力目前还没有补齐，因此不能把当前方案视为最终生产级方案。

### 5.1 密钥管理

- 当前 Java 与 Python 使用共享对称密钥
- 尚未接入密钥管理系统
- 尚未支持密钥轮换
- 尚未支持多版本密钥兼容校验
- 当前代码已具备 `HS256/RS256 + kid` 双模式迁移底座

工业化建议：

- 优先升级为非对称签名方案，例如 `RS256`
- Java 持有私钥签发
- Python 和网关使用公钥校验
- 配合 `kid` 支持密钥轮换
- 详细设计见 [jwt-asymmetric-key-rotation-design.md](/mnt/disk2/pixels-rover/docs/jwt-asymmetric-key-rotation-design.md:1)

### 5.2 Token 生命周期治理

- 当前 Java `auth-service` 已支持 refresh token 轮换
- 当前 Java `auth-service` 已支持基于会话表的 token 撤销
- 当前 Java `auth-service` 已支持设备级会话管理
- Python `analysis-service` 仍未回源校验会话撤销状态，因此跨服务“立即失效”仍需后续在网关或统一 introspection 层补齐

工业化建议：

- refresh token 使用轮换策略
- 建立 token 黑名单或会话表
- 支持主动登出、强制下线、单设备/多设备策略

### 5.3 前端存储安全

- ✅ 已从 `localStorage` 迁移到 `HttpOnly Secure SameSite` Cookie 方案
- 网关 NJS（`cookie_handler.js`）负责 login/refresh 响应的 Cookie 注入（`access_token`、`refresh_token`、`logged_in`、`XSRF-TOKEN`）和 logout 的 Cookie 清除
- `access_token` 和 `refresh_token` 为 `HttpOnly; Secure; SameSite=Strict`，前端 JS 不可读取
- `logged_in`（非 HttpOnly）供前端检测登录状态，`XSRF-TOKEN`（非 HttpOnly）供前端读取并通过 `X-XSRF-TOKEN` header 实现 double-submit CSRF 防护
- Java `CookieHelper` 已回归只读职责，`AuthController` 不再操作 `HttpServletResponse`
- 前端 `cookie.ts` 通过 `isLoggedInCookie()` 检测登录状态，`client.ts` 自动注入 CSRF header

后续可继续加固：

- 配合严格 CSP 策略进一步降低 XSS 风险
- 评估 Cookie 的 `SameSite` 策略是否需要根据部署拓扑调整

### 5.4 网关与统一入口

- ✅ 已引入 Nginx API Gateway（`gateway/`），生产环境提供统一入口
- ✅ 网关层已统一处理 CORS（`snippets/cors.conf`）、鉴权透传（`auth_request`）、分级限流（`limit_req`）和 JSON 审计日志
- ✅ 路由规则：`/api/v1/auth/*` → auth-service，`/api/*` → analysis-service，`/` → frontend
- ✅ 前端开发期通过 Vite proxy 代理，部署期由 gateway 统一代理
- ✅ CSRF 验证在网关层完成（NJS `verifyCsrf`），Java `SecurityConfig` 已禁用 CSRF

后续可继续增强：

- 评估是否需要在网关层补齐跨服务 token 撤销的实时校验（当前 Python 侧未回源校验会话撤销状态）
- 增加更细粒度的限流策略（按用户、按 API 分组）

### 5.5 错误契约与审计

- Java 和 Python 的核心鉴权与主分析链路错误结构已完成统一，但还没有做到全量覆盖
- `requestId` 已贯通，但日志字段、监控字段和前端展示仍需继续规范
- 尚未补齐安全审计日志

工业化建议：

- 统一认证失败、权限失败、token 过期、token 类型错误的错误码
- 每次认证和分析请求都记录 `requestId`
- 增加登录、刷新、失败校验、越权访问的审计日志

### 5.6 测试覆盖

- 目前已覆盖 Java 认证模块基础测试与 JWT 契约测试
- 已覆盖 Python 鉴权单元测试，包括缺少 token、错误 issuer、错误 token 类型、缺失 `uid` 等关键场景
- Python 接口级鉴权测试、跨服务联调测试和端到端测试仍不足

工业化建议：

- 增加 Python 侧 token 校验测试
- 增加 Python 侧受保护接口鉴权测试
- 增加前端 refresh 流程测试
- 增加 Java 签发、Python 校验、前端自动刷新这一整条链路的集成测试

## 6. 推荐的工业生产演进路径

### 阶段 1：当前已完成的基础闭环

- Java 签发 JWT
- 前端 Bearer 透传
- Python 校验 JWT
- 前端 401 自动 refresh

### 阶段 2：达到可上线的基础生产标准

- ✅ 统一错误码与错误响应
- ✅ 接入 `requestId`
- 增加 Python 鉴权测试和联调测试
- 区分匿名接口与受保护接口文档
- ✅ 补充安全审计日志（网关 JSON 审计日志）
- ✅ 落地 refresh token 轮换、token 撤销与设备级会话管理
- ✅ 引入统一网关，统一处理 CORS、鉴权透传、限流
- ✅ 前端存储迁移到 HttpOnly Cookie，CSRF double-submit 防护在网关层完成

### 阶段 3：达到更成熟的工业生产标准

- ✅ 升级非对称签名（RS256 + kid）
- 密钥轮换生产级落地
- 权限模型与角色模型
- 组织/租户级访问控制
- 跨服务 token 撤销实时校验（网关或统一 introspection 层）

## 8. 配套设计文档

- 统一鉴权与接口边界规范：[auth-identity-spec.md](/mnt/disk2/pixels-rover/docs/auth-identity-spec.md:1)
- JWT 非对称签名与密钥轮换方案：[jwt-asymmetric-key-rotation-design.md](/mnt/disk2/pixels-rover/docs/jwt-asymmetric-key-rotation-design.md:1)
- JWT 首次切换到 RS256 的操作说明：[jwt-rs256-cutover.md](/mnt/disk2/pixels-rover/docs/jwt-rs256-cutover.md:1)
- 预发环境密钥轮换演练 Runbook：[jwt-preprod-rotation-drill.md](/mnt/disk2/pixels-rover/docs/jwt-preprod-rotation-drill.md:1)

## 7. 当前结论

当前项目已经具备“统一鉴权主链路已打通”的基础，但还不应被表述为“工业生产直接可用的最终版本”。

更准确的判断是：

- 当前已经完成第一阶段可运行方案
- 已经具备继续升级为生产级方案的正确基础
- 下一步应围绕密钥管理、错误契约、日志审计、测试覆盖和网关治理继续推进
