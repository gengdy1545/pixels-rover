# Pixels Rover 统一 API 与服务契约规范

## 1. 目标

本文档定义 Pixels Rover 跨服务的统一 API 契约，包括：

- 统一响应结构与错误码体系
- 超时策略、重试策略与异常映射规则
- 字段命名规范与时间格式规范

所有 Java `auth-service`、Python `analysis-service` 和前端 `frontend` 必须遵守本规范。

## 2. 统一响应结构

### 2.1 成功响应

```json
{
  "code": 200,
  "message": "success",
  "data": { ... },
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "apiVersion": "v1"
}
```

| 字段         | 类型     | 必填 | 说明                                |
|--------------|----------|------|-------------------------------------|
| `code`       | `int`    | 是   | HTTP 状态码或业务状态码，成功为 200 |
| `message`    | `string` | 是   | 人类可读的消息                      |
| `data`       | `any`    | 否   | 业务数据载荷                        |
| `requestId`  | `string` | 是   | 请求追踪 ID                         |
| `apiVersion` | `string` | 是   | API 版本号（如 `v1`）               |

### 2.2 错误响应

```json
{
  "code": 40100,
  "message": "Authentication required",
  "errorCode": "AUTHENTICATION_REQUIRED",
  "requestId": "550e8400-e29b-41d4-a716-446655440000"
}
```

| 字段        | 类型     | 必填 | 说明                                        |
|-------------|----------|------|---------------------------------------------|
| `code`      | `int`    | 是   | 业务错误码（见 §3）                         |
| `message`   | `string` | 是   | 人类可读的错误描述                          |
| `errorCode` | `string` | 是   | 稳定的跨服务错误码字符串（见 §3）           |
| `requestId` | `string` | 是   | 请求追踪 ID                                 |

### 2.3 SSE 流式响应

SSE 流式响应不使用上述 JSON 包装，保留标准 SSE 事件格式：

```
event: <event_type>
data: <json_payload>
```

SSE 流中的错误事件使用 `event: error`，`data` 中包含 `code`、`message`、`errorCode`。

## 3. 统一错误码体系

### 3.1 错误码分层

错误码采用 5 位数字编码，前 3 位对应 HTTP 状态码语义，后 2 位为细分编号：

| 分类         | 范围        | HTTP 状态码 | 说明                     |
|--------------|-------------|-------------|--------------------------|
| 参数错误     | 400xx       | 400         | 请求参数不合法           |
| 认证错误     | 401xx       | 401         | 身份认证失败             |
| 权限错误     | 403xx       | 403         | 已认证但无权限           |
| 资源错误     | 404xx       | 404         | 资源不存在               |
| 冲突错误     | 409xx       | 409         | 资源冲突                 |
| 依赖错误     | 502xx       | 502         | 上游服务不可用或返回错误 |
| 系统错误     | 500xx       | 500         | 内部未知错误             |

### 3.2 完整错误码清单

| 数字码  | 字符串码                 | HTTP 状态码 | 说明                                     |
|---------|--------------------------|-------------|------------------------------------------|
| `40000` | `INVALID_ARGUMENT`       | 400         | 请求参数缺失、格式错误或校验失败         |
| `40100` | `AUTHENTICATION_REQUIRED`| 401         | 缺少 Bearer token 或 token 已过期        |
| `40101` | `INVALID_CREDENTIALS`    | 401         | 用户名或密码错误                         |
| `40102` | `INVALID_TOKEN`          | 401         | token 无效、签名错误或已被撤销           |
| `40103` | `INVALID_TOKEN_TYPE`     | 401         | token 类型不匹配（如用 refresh 当 access）|
| `40300` | `ACCESS_DENIED`          | 403         | 已认证但无权访问该资源                   |
| `40400` | `RESOURCE_NOT_FOUND`     | 404         | 请求的资源不存在或对当前用户不可见       |
| `40500` | `METHOD_NOT_ALLOWED`     | 405         | HTTP 方法不被支持                        |
| `40900` | `RESOURCE_CONFLICT`      | 409         | 资源冲突（如用户名已存在）               |
| `50000` | `INTERNAL_ERROR`         | 500         | 服务内部未知错误                         |
| `50200` | `DEPENDENCY_ERROR`       | 502         | 上游依赖服务不可用或返回错误             |

### 3.3 错误码使用规则

1. **所有错误响应必须同时包含数字 `code` 和字符串 `errorCode`**，前端优先使用 `errorCode` 做分支判断
2. **Java 服务**通过 `ErrorCode` 常量类定义数字码，`ErrorCodeName` 类自动映射字符串码
3. **Python 服务**通过 `error_codes.py` 定义数字码和字符串码，`resolve_error_code_name()` 自动映射
4. **新增错误码**必须同时在 Java `ErrorCode` + `ErrorCodeName` 和 Python `error_codes.py` 中注册
5. **前端**通过 `ApiResponse.errorCode` 字段判断错误类型，不应依赖 `message` 文本

### 3.4 异常到错误码的映射规则

#### Java 服务异常映射（由 `GlobalExceptionHandler` 统一处理）

| 异常类型                                  | 错误码              | 说明                     |
|-------------------------------------------|---------------------|--------------------------|
| `MethodArgumentNotValidException`         | `INVALID_ARGUMENT`  | Bean 校验失败            |
| `BindException`                           | `INVALID_ARGUMENT`  | 绑定校验失败             |
| `MissingServletRequestParameterException` | `INVALID_ARGUMENT`  | 缺少必填参数             |
| `CaptchaException`                        | `INVALID_ARGUMENT`  | 验证码错误               |
| `AccessDeniedException`                   | `ACCESS_DENIED`     | Spring Security 权限拒绝 |
| `HttpRequestMethodNotSupportedException`  | `METHOD_NOT_ALLOWED`| HTTP 方法不支持          |
| `ServiceException`（带 code）             | 对应 code           | 业务异常                 |
| `ServiceException`（无 code）             | `INTERNAL_ERROR`    | 未分类业务异常           |
| `WebClientResponseException`              | `INTERNAL_ERROR`    | 上游服务返回错误         |
| `WebClientRequestException`               | `INTERNAL_ERROR`    | 上游服务连接失败         |
| `DemoModeException`                       | `ACCESS_DENIED`     | 演示模式限制             |
| `RuntimeException`                        | `INTERNAL_ERROR`    | 未知运行时异常           |
| `Exception`                               | `INTERNAL_ERROR`    | 未知系统异常             |

#### Python 服务异常映射（由 `main.py` 全局异常处理器统一处理）

| 异常类型                 | 错误码             | 说明                     |
|--------------------------|--------------------|--------------------------|
| `RequestValidationError` | `INVALID_ARGUMENT` | Pydantic 请求体校验失败  |
| `HTTPException`          | 取决于 detail      | 业务异常，detail 中携带 code/errorCode |
| `Exception`              | `INTERNAL_ERROR`   | 未知异常                 |

## 4. 超时策略

### 4.1 各层超时配置

| 层级                     | 超时时间    | 配置位置                                    | 说明                                     |
|--------------------------|-------------|---------------------------------------------|------------------------------------------|
| 前端 HTTP 请求           | 30s         | `apps/frontend/src/services/api.ts`         | Axios `timeout: 30000`                   |
| 前端 SSE 流式请求        | 无硬超时    | 前端 `fetch` 调用                           | 依赖后端 `max_wall_time_sec` 控制        |
| Java → 上游 Pixels Server| 30s         | WebClient 默认                              | Metadata/Query/TextToSQL 转发            |
| Python 分析任务总耗时    | 180s        | `AnalysisRequest.max_wall_time_sec`         | 单次分析任务最大执行时间                 |
| Python LLM 单次调用      | 60s         | `Settings.llm_timeout`                      | 单次 LLM API 调用超时                    |
| Python 数据库连接        | 默认        | SQLAlchemy 连接池默认                       | 数据库操作超时                           |

### 4.2 超时策略原则

1. **前端超时 > 后端超时**：前端 HTTP 超时必须大于后端处理超时，避免前端先断开而后端仍在处理
2. **SSE 流式请求不设前端硬超时**：分析任务由后端 `max_wall_time_sec` 控制，前端通过 SSE 事件感知完成或超时
3. **上游转发超时独立配置**：Java 服务转发到 Pixels Server 的超时独立于前端超时
4. **LLM 调用超时独立配置**：LLM 单次调用超时独立于分析任务总超时

### 4.3 超时错误处理

- 前端 HTTP 超时：Axios 抛出超时错误，前端展示 "Request timed out, please try again"
- Java 上游超时：`WebClientRequestException` → `INTERNAL_ERROR`，message 包含 "service unavailable"
- Python 分析超时：分析服务通过 SSE 发送 `event: error`，包含超时信息
- Python LLM 超时：LLM 客户端抛出超时异常，分析服务捕获并通过 SSE 报告

## 5. 重试策略

### 5.1 各层重试规则

| 层级                     | 重试策略                                    | 说明                                     |
|--------------------------|---------------------------------------------|------------------------------------------|
| 前端 401 自动刷新        | 自动重试 1 次                               | 收到 401 后自动调用 refresh，成功后重放原请求 |
| 前端其他错误             | 不自动重试                                  | 由用户手动重试                           |
| Java → 上游服务          | 不自动重试                                  | 上游错误直接返回给调用方                 |
| Python 分析任务          | 不自动重试                                  | 分析任务失败后由用户重新提交             |
| Python LLM 调用          | 由 LLM 客户端库内置重试                     | litellm 内置指数退避重试                 |

### 5.2 重试策略原则

1. **幂等性**：只有幂等请求（GET、PUT）才适合自动重试，非幂等请求（POST）不应自动重试
2. **401 刷新重试**：前端收到 401 时自动尝试刷新 token 并重放，最多 1 次
3. **不重试业务错误**：`INVALID_ARGUMENT`、`RESOURCE_NOT_FOUND`、`ACCESS_DENIED` 等业务错误不应重试
4. **可重试的错误**：仅 `DEPENDENCY_ERROR`（上游暂时不可用）和网络错误适合重试
5. **退避策略**：如果未来引入自动重试，必须使用指数退避（exponential backoff），避免雪崩

### 5.3 前端 401 刷新流程

```
Request → 401 → refreshAccessToken() → 成功 → 重放原请求
                                      → 失败 → 跳转登录页
```

- 并发请求遇到 401 时，只触发一次 refresh，其他请求排队等待
- refresh 成功后，排队请求全部重放
- refresh 失败后，排队请求全部拒绝，跳转登录页

## 6. 字段命名规范

### 6.1 命名风格

| 层级              | 命名风格      | 示例                          | 说明                                     |
|-------------------|---------------|-------------------------------|------------------------------------------|
| API 响应 JSON     | `camelCase`   | `requestId`, `errorCode`      | 前端友好，与 JavaScript 惯例一致         |
| Python 内部代码   | `snake_case`  | `request_id`, `error_code`    | Python 惯例                              |
| Java 内部代码     | `camelCase`   | `requestId`, `errorCode`      | Java 惯例                                |
| 数据库字段        | `snake_case`  | `created_at`, `user_id`       | SQL 惯例                                 |
| HTTP 请求头       | `X-Title-Case`| `X-Request-Id`, `Authorization`| HTTP 惯例                               |

### 6.2 API JSON 字段命名规则

1. **所有 API 响应 JSON 字段统一使用 `camelCase`**
2. Python 服务在序列化 JSON 时，将内部 `snake_case` 转换为 `camelCase`
3. Java 服务默认使用 `camelCase`，无需额外转换
4. **例外**：Python 分析服务中部分历史接口的 `data` 载荷内部字段仍使用 `snake_case`（如 `session_id`、`source_table`），这些字段在后续版本中逐步迁移为 `camelCase`

### 6.3 统一字段名清单

以下字段在所有服务中必须使用统一名称：

| 字段名         | 类型     | 说明                                     |
|----------------|----------|------------------------------------------|
| `requestId`    | `string` | 请求追踪 ID                              |
| `code`         | `int`    | 状态码                                   |
| `message`      | `string` | 消息描述                                 |
| `data`         | `any`    | 数据载荷                                 |
| `errorCode`    | `string` | 错误码字符串                             |
| `userId`       | `int`    | 用户 ID                                  |
| `sessionId`    | `string` | 会话 ID                                  |
| `createdAt`    | `string` | 创建时间（ISO 8601）                     |
| `updatedAt`    | `string` | 更新时间（ISO 8601）                     |
| `completedAt`  | `string` | 完成时间（ISO 8601）                     |
| `expiredAt`    | `string` | 过期时间（ISO 8601）                     |
| `apiVersion`   | `string` | API 版本号（如 `v1`）                    |

## 7. 时间格式规范

### 7.1 统一时间格式

**所有 API 响应中的时间字段统一使用 ISO 8601 格式，带时区信息：**

```
2024-12-25T14:30:00Z          # UTC
2024-12-25T22:30:00+08:00     # 带时区偏移
```

### 7.2 各层时间处理

| 层级              | 格式                          | 说明                                     |
|-------------------|-------------------------------|------------------------------------------|
| API 响应          | ISO 8601 (`yyyy-MM-dd'T'HH:mm:ss'Z'`) | 统一使用 UTC 或带时区偏移       |
| Java 内部         | `java.time.Instant` 或 `OffsetDateTime` | 避免使用 `java.util.Date`      |
| Python 内部       | `datetime` with `timezone.utc`| 避免使用 naive datetime                  |
| 数据库存储        | `TIMESTAMP` / `DATETIME`      | 存储 UTC 时间                            |
| 前端展示          | 本地时区格式化                | 使用 `dayjs` 或 `Intl.DateTimeFormat`    |

### 7.3 时间格式规则

1. **API 响应中的时间一律使用 ISO 8601 字符串**，不使用 Unix 时间戳
2. **存储和传输使用 UTC**，展示时由前端转换为用户本地时区
3. **Java 服务**使用 `Instant.now()` 获取当前时间，序列化时使用 Jackson 的 ISO 8601 格式
4. **Python 服务**使用 `datetime.now(timezone.utc)` 获取当前时间，序列化时调用 `.isoformat()`
5. **持续时间**使用毫秒整数（如 `wallTimeMs: 1234`），不使用 ISO 8601 Duration

## 8. 请求头规范

### 8.1 统一请求头

| 请求头            | 必填 | 说明                                     |
|-------------------|------|------------------------------------------|
| `Authorization`   | 条件 | `Bearer <access_token>`，受保护接口必填  |
| `X-Request-Id`    | 推荐 | 请求追踪 ID，前端生成或服务端自动补充    |
| `Content-Type`    | 是   | `application/json`                       |
| `X-XSRF-TOKEN`    | 条件 | CSRF 双重提交 token，写操作时携带        |

### 8.2 响应头

| 响应头            | 说明                                     |
|-------------------|------------------------------------------|
| `X-Request-Id`    | 回传请求追踪 ID                          |

## 9. API 版本管理规范

### 9.1 版本标识

所有 API 响应中包含 `apiVersion` 字段，标识当前 API 的版本号。版本号与 URL 路径前缀保持一致。

```json
{
  "code": 200,
  "message": "success",
  "data": { ... },
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "apiVersion": "v1"
}
```

| 字段         | 类型     | 必填 | 说明                                     |
|--------------|----------|------|------------------------------------------|
| `apiVersion` | `string` | 是   | API 版本号，与 URL 路径前缀一致（如 `v1`） |

### 9.2 版本演进规则

#### 向后兼容变更（不需要升级版本号）

以下变更被视为向后兼容，可以在当前版本中直接进行：

- **新增**响应字段（客户端应忽略未知字段）
- **新增** API 端点
- **新增**可选请求参数（带默认值）
- **新增**错误码
- **放宽**请求参数的校验规则（如从必填改为可选）

#### 破坏性变更（必须升级版本号）

以下变更被视为破坏性变更，必须通过新版本（如 `/api/v2/`）引入：

- **删除或重命名**现有响应字段
- **删除或重命名**现有 API 端点
- **修改**现有字段的数据类型
- **修改**现有端点的 HTTP 方法
- **收紧**请求参数的校验规则（如从可选改为必填）
- **修改**错误码的语义

### 9.3 版本迁移路径

当需要引入破坏性变更时，遵循以下迁移流程：

1. **新版本并行发布**：在 `/api/v2/` 路径下发布新版本端点，旧版本 `/api/v1/` 继续可用
2. **标记废弃**：在旧版本响应中增加 `deprecated: true` 字段，并在文档中标注废弃时间
3. **迁移期**：至少保留 2 个版本并行运行，给客户端充足的迁移时间
4. **下线旧版本**：迁移期结束后，旧版本返回 `410 Gone` 并引导客户端升级

### 9.4 实现要求

1. **Java 服务**：`ApiResponse` 类中增加 `apiVersion` 字段，默认值为 `"v1"`
2. **Python 服务**：`api_success()` 和 `api_error()` 函数返回值中增加 `apiVersion` 字段
3. **前端**：`ApiResponse` 类型定义中增加 `apiVersion` 字段
4. **SSE 流式响应**：SSE 事件不包含 `apiVersion`，版本信息通过 URL 路径隐含

## 10. 实现状态

### 10.1 已完成

- [x] Java 和 Python 统一响应结构 `code/message/data/requestId/errorCode/apiVersion`
- [x] Java `GlobalExceptionHandler` 覆盖所有异常类型并映射到统一错误码
- [x] Python 全局异常处理器覆盖 `HTTPException`、`RequestValidationError`、`Exception`
- [x] Java 所有 Controller 使用 `ApiResponse` 返回统一格式
- [x] Java 上游转发 Controller（Metadata/Query/TextToSQL）使用具体错误码区分上游错误
- [x] Python 所有 API 路由使用 `api_success`/`api_error` 返回统一格式
- [x] 前端 `ApiResponse` 类型定义与响应拦截器统一处理
- [x] 前端 401 自动刷新 + 并发请求排队机制
- [x] `X-Request-Id` 全链路贯通
- [x] 错误码体系完整定义（含 `DEPENDENCY_ERROR`）
- [x] API 版本管理规范（§9）及 `apiVersion` 字段全链路贯通

### 10.2 后续待完成

- [ ] Python 分析服务 `data` 载荷内部字段从 `snake_case` 迁移为 `camelCase`
- [ ] Java 服务时间字段从 `java.sql.Timestamp` 迁移为 `java.time.Instant`
- [ ] 引入网关后，在网关层统一超时、限流和重试策略
- [ ] 前端引入可重试错误的自动重试机制（针对 `DEPENDENCY_ERROR`）
