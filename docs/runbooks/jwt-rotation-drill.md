# Pixels Rover JWT RS256 切换与密钥轮换 Runbook

> 本文档是可执行的运维手册。对应的设计背景与决策见 [`../design/jwt-rotation.md`](../design/jwt-rotation.md)。
>
> **架构前提（必读）**：本 Runbook 基于 **gateway-centric 架构**——JWT 的签发与校验只发生在 `auth-service` 进程内部，`gateway` 通过 `introspect` 消费身份，`assistant-service` 只消费 `X-Auth-*` 头。因此**不涉及**向 Python 服务或 gateway 分发公钥。如果未来架构回到"业务服务自校验 JWT"形态，本 Runbook 需要整体重写。

本 Runbook 用于指导在**预发或生产环境**完成：

- 首次 `HS256 → RS256` 切换
- `kid` 生效验证
- 多公钥并存验证（均在 auth-service 内部）
- 密钥轮换
- 回滚

适用场景：

- 预发演练（按全部阶段执行，目的是把流程跑通）
- 生产切换（按阶段 C → D 执行，按 E → F 推进日常轮换）

## 1. 演练目标

本次演练需要验证：

1. `auth-service` 能以 `RS256` 签发 access token 和 refresh token
2. `auth-service` 能根据 `kid` 自校验 token（在 `/api/v1/auth/refresh` 与 `POST /api/internal/auth/introspect` 路径上）
3. 浏览器登录、刷新 token、调用分析接口（经 gateway introspect 通过后注入 `X-Auth-*`）不受影响
4. 新旧公钥在 auth-service 内部可并存校验
5. 切换 `active-kid` 后新 token 使用新密钥签发
6. 旧 token 在旧公钥保留期内仍可用
7. 回滚到旧 `kid` 或旧配置时系统可恢复

## 2. 演练前准备

### 2.1 代码前提

确认目标环境部署的版本已经包含：

- `auth-service` 的 `HS256/RS256 + kid` 支持
- `auth-service` 内部多公钥校验能力
- `scripts/generate-jwt-rsa-keys.sh`

**不再要求**：

- `assistant-service` 的 JWT 校验能力（业务服务不参与 JWT 校验）
- gateway 的 JWT 校验能力（gateway 通过 introspect 消费身份）
- `GET /api/v1/auth/jwks`（当前系统内部不消费 JWKS，相关端点已计划下线，见 [`../../.notes/todolist.md`](../../.notes/todolist.md)）

### 2.2 环境前提

确认目标环境具备：

- 可单独更新 `auth-service` 的配置（多副本部署时要确保所有副本同步）
- 可查看 `auth-service` 日志
- 可查看 gateway access log（用于观察 introspect 子请求结果）
- 可通过浏览器完成登录、刷新 token 和分析请求

### 2.3 数据前提

准备至少 1 个可登录测试账号，并确认：

- 能正常登录
- 能正常访问分析接口
- 能正常 refresh token

## 3. 演练角色分工

建议至少两人配合：

- 执行人：修改配置、发布服务、发起验证
- 观察人：查看日志、记录请求结果、确认回滚点

## 4. 演练分阶段步骤

### 阶段 A：基线验证

在任何切换前，先记录当前基线：

1. 登录一次，保存当前 access token 和 refresh token cookie（注意 HttpOnly，需要从 gateway 日志或调试手段获取）
2. 访问 `GET /api/v1/auth/me`
3. 访问一个受保护业务接口，例如 `GET /api/v1/analysis/backends`
4. 执行一次 refresh token（`POST /api/v1/auth/refresh`）
5. 记录当前 token header 中的：
   - `alg`
   - `kid`（`HS256` 基线下可能为空）
6. 记录 gateway 与 auth-service 日志中的 `X-Request-Id`

预期：

- 当前链路全部成功
- 若环境仍是 `HS256`，可作为切换前对照组

### 阶段 B：生成两套 RSA 密钥

生成两套密钥（示例 `kid` 命名按月度 + 字母后缀，可按实际命名约定调整）：

- `preprod-rsa-a`
- `preprod-rsa-b`

示例：

```bash
bash scripts/generate-jwt-rsa-keys.sh /secure/preprod/jwt-keys preprod-rsa-a
bash scripts/generate-jwt-rsa-keys.sh /secure/preprod/jwt-keys preprod-rsa-b
```

准备结果：

- `preprod-rsa-a-private.pem`
- `preprod-rsa-a-public.pem`
- `preprod-rsa-b-private.pem`
- `preprod-rsa-b-public.pem`

> 不再需要 `*-public-keys.json` 文件或 `all-public-keys.json` 合并产物——公钥只在 auth-service 自身配置里使用。下一阶段直接以 PEM 文件路径或环境变量下发。

### 阶段 C：先发布公钥，不切签发（仅 auth-service）

将两把公钥都发布到 **`auth-service` 自身**的配置目录或配置中心，并保持 `HS256` 签发不变。

建议 auth-service 配置：

```properties
jwt.algorithm=HS256
jwt.issuer=pixels-rover-auth-service
jwt.secret=<existing HS256 secret>
jwt.public-keys.preprod-rsa-a=/secure/preprod/jwt-keys/preprod-rsa-a-public.pem
jwt.public-keys.preprod-rsa-b=/secure/preprod/jwt-keys/preprod-rsa-b-public.pem
```

注意：

- 这一步仅把**潜在**的 RS256 校验公钥预加载进 `auth-service` 内存；仍然用 HS256 签发；
- 发布后确认 `auth-service` 服务可正常启动、旧 HS256 token 可继续通过 `introspect`；
- **不**需要同时更新 `assistant-service` 或 gateway 配置。

### 阶段 D：auth-service 首次切换到 RS256

将 `auth-service` 切换为：

```properties
jwt.algorithm=RS256
jwt.active-kid=preprod-rsa-a
jwt.private-key-path=/secure/preprod/jwt-keys/preprod-rsa-a-private.pem
jwt.public-keys.preprod-rsa-a=/secure/preprod/jwt-keys/preprod-rsa-a-public.pem
jwt.public-keys.preprod-rsa-b=/secure/preprod/jwt-keys/preprod-rsa-b-public.pem
```

发布 `auth-service` 后执行：

1. 通过浏览器完成登录（实际的 access token / refresh token 对浏览器不可见，以 HttpOnly cookie 下发）
2. 从 `auth-service` 日志中捕获新签发 token 的 header 摘要（不要把完整 token 打印到日志）
3. 确认：
   - `alg=RS256`
   - `kid=preprod-rsa-a`
4. 校验目标（注意：下游服务**不**直接校验 token header）：
   - `GET /api/v1/auth/me`（经 gateway introspect → auth-service → 注入 `X-Auth-*` → auth-service 自身 me 端点）
   - `GET /api/v1/analysis/backends`（经 gateway introspect → 注入 `X-Auth-*` → assistant-service）
   - `POST /api/v1/analysis`（同上）
5. 执行 refresh token（`POST /api/v1/auth/refresh`）
6. 确认刷新出的 access token 仍为：
   - `alg=RS256`
   - `kid=preprod-rsa-a`
7. 观察 gateway access log 中 introspect 子请求返回 `active=true` 且带用户身份字段

### 阶段 E：验证多公钥并存

保持 `auth-service` 内部持有：

- `preprod-rsa-a`
- `preprod-rsa-b`

但此时 `auth-service` 仍用：

- `active-kid=preprod-rsa-a`

验证：

1. 使用阶段 D 中签发的 token 调用若干受保护接口
2. 确认旧 token 继续可用（经由 introspect 被成功识别）
3. 在 `auth-service` 内部确认 `JwtVerificationKeyProvider` 按 `kid` 成功选择到对应公钥（可通过调试日志或单元测试协同确认）

> 不再验证 `GET /api/v1/auth/jwks`——该端点已计划下线，且 gateway / assistant-service 本来也不消费 JWKS。

### 阶段 F：模拟轮换切到新 kid

将 `auth-service` 切换为：

```properties
jwt.algorithm=RS256
jwt.active-kid=preprod-rsa-b
jwt.private-key-path=/secure/preprod/jwt-keys/preprod-rsa-b-private.pem
jwt.public-keys.preprod-rsa-a=/secure/preprod/jwt-keys/preprod-rsa-a-public.pem
jwt.public-keys.preprod-rsa-b=/secure/preprod/jwt-keys/preprod-rsa-b-public.pem
```

发布后执行：

1. 重新登录获取新 token
2. 从 auth-service 日志确认新 token：
   - `alg=RS256`
   - `kid=preprod-rsa-b`
3. 用新 token 访问受保护接口（通过 gateway introspect）
4. 再使用阶段 D 里签发的旧 token 调用受保护接口

预期：

- 新 token 正常通过 introspect
- 旧 token 也仍然通过 introspect（依赖 `preprod-rsa-a` 公钥仍在 auth-service 内部并存）

这一步就是"多公钥并存 + 切 active-kid"的关键验证。

### 阶段 G：验证 refresh token 兼容

在切到 `preprod-rsa-b` 后：

1. 使用阶段 D 获取的旧 refresh token 调用 `POST /api/v1/auth/refresh`
2. 确认 refresh 仍成功
3. 确认新 access token 由当前激活 `kid=preprod-rsa-b` 签发

这一步非常关键，因为它验证了：

- 旧 refresh token 依赖旧公钥仍可被识别
- 新 access token 已被新私钥签发

## 5. 演练完成条件

只有同时满足下面条件，才算演练成功：

- 首次 `RS256` 切换成功
- `kid` 正常写入 token header
- auth-service 能根据 `kid` 自校验 token
- 新旧 token 能在并存窗口内同时被接受
- refresh token 兼容验证成功
- gateway 的 introspect 路径全程正确返回 `active=true` + 身份字段
- 回滚方案已验证

## 6. 回滚步骤

如果任一步失败，按下面顺序回滚：

1. `auth-service`
   - 恢复到上一个稳定配置
   - 恢复旧 `jwt.algorithm`
   - 恢复旧 `active-kid` 或旧 `HS256` 配置
2. gateway / assistant-service
   - **通常无需改动**；它们不参与 JWT 校验
3. 前端
   - 一般无需改动
   - 如用户本地 cookie 对应的 token 已不兼容，可提示重新登录

回滚后重新验证：

- 登录
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/refresh`
- 一个受保护业务接口

## 7. 观察项清单

演练期间建议记录：

- `auth-service` 登录接口日志
- `auth-service` refresh 接口日志
- `auth-service` introspect 接口日志（`active=true/false`、`errorCode`）
- gateway access log 中 introspect 子请求结果
- `X-Request-Id`
- token 的 `alg` / `kid`
- 切换前后成功率

## 8. 演练后的决策

演练结束后应明确给出结论：

### 结果 A：通过

说明：

- 目标环境可支撑 `RS256 + kid`
- 预发通过后可以进入生产切换审批

### 结果 B：部分通过

说明：

- 首次切换成功
- 但轮换或 refresh 兼容存在问题

动作：

- 修复后重新演练

### 结果 C：失败

说明：

- 回滚有效
- 生产切换暂缓

动作：

- 记录故障点
- 修复后重新安排演练

## 9. 建议的演练输出物

演练结束后建议至少沉淀：

- 演练时间
- 参与人
- 使用的 `kid`
- 切换前后配置摘要
- 成功/失败结论
- 遗留问题列表
- 是否允许进入生产切换

## 10. 配套脚本

- 密钥生成脚本：[`../../scripts/generate-jwt-rsa-keys.sh`](../../scripts/generate-jwt-rsa-keys.sh)（已存在）

> 早期版本曾引用 `scripts/merge-jwt-public-keys.sh` 与 `scripts/preprod-rotation-drill.sh`。前者在 gateway-centric 架构下**彻底不再需要**（不存在跨服务公钥合并场景，移除）；后者作为分阶段自动化愿景，目前仍由人工按本 Runbook 驱动执行。若需要落成脚本，建议作为独立工程任务推动，而不是在演练现场补写。
