# Pixels Rover JWT 非对称签名与密钥轮换方案

## 1. 目标

本方案用于将 Pixels Rover 当前的对称签名 JWT 方案：

- Java `auth-service` 与 Python `analysis-service` 共享 `HS256` 密钥

升级为更适合生产环境的非对称签名与密钥轮换方案：

- Java `auth-service` 使用私钥签发 JWT
- Python `analysis-service`、未来网关与其他消费方使用公钥校验 JWT
- 支持多把公钥并存
- 支持通过 `kid` 平滑轮换

## 2. 当前问题

当前方案的主要风险有：

- Java 和 Python 共享同一个对称密钥，任何一个服务泄露密钥都会同时失去签发与校验边界
- 无法只把“校验能力”安全地下发给 Python 或网关
- 不支持多版本密钥并行校验
- 密钥轮换时无法做到平滑切换

这意味着当前方案适合开发与第一阶段联调，但不适合长期生产使用。

## 3. 目标方案概览

推荐采用：

- JWT 签名算法：`RS256`
- 签发方：Java `auth-service`
- 校验方：Python `analysis-service`、未来网关
- 密钥标识：使用 `kid`
- 公钥发布方式：`JWKS` 或内部只读公钥配置

统一设计如下：

1. Java 只持有私钥与当前激活 `kid`
2. Java 在 JWT header 中写入 `kid`
3. Python 根据 `kid` 选择对应公钥校验
4. 轮换期间允许多个历史公钥并存校验
5. 新 token 只使用新的私钥签发
6. 历史 token 在自然过期后再移除旧公钥

## 4. 目标 JWT 结构

### 4.1 Header

JWT header 至少包含：

```json
{
  "alg": "RS256",
  "typ": "JWT",
  "kid": "2026-rot-a"
}
```

### 4.2 Payload

payload 继续保留当前核心字段：

- `iss`: `pixels-rover-auth-service`
- `sub`: 用户邮箱
- `uid`: 用户 ID
- `type`: `access` 或 `refresh`
- `iat`
- `exp`

如果后续接入权限模型，可继续增加：

- `roles`
- `tenantId`
- `sessionId`

但第一阶段不要把权限扩展和密钥轮换耦合在一起。

## 5. 密钥模型设计

### 5.1 Java `auth-service`

Java 侧新增以下配置概念：

- `jwt.algorithm=RS256`
- `jwt.issuer=pixels-rover-auth-service`
- `jwt.active-kid=2026-rot-a`
- `jwt.private-key-pem=...`
- `jwt.public-keys[2026-rot-a]=...`
- `jwt.public-keys[2026-rot-b]=...`

职责划分：

- 私钥：仅 Java 持有，只用于签发
- 公钥：Java 可持有用于自校验，也可从统一配置源读取
- 激活 `kid`：决定新签发 token 使用哪把私钥

### 5.2 Python `analysis-service`

Python 侧不持有私钥，只需要：

- `ROVER_JWT_ALGORITHM=RS256`
- `ROVER_JWT_ISSUER=pixels-rover-auth-service`
- `ROVER_JWT_PUBLIC_KEYS_JSON={...}`

其中 `ROVER_JWT_PUBLIC_KEYS_JSON` 建议结构为：

```json
{
  "2026-rot-a": "-----BEGIN PUBLIC KEY----- ...",
  "2026-rot-b": "-----BEGIN PUBLIC KEY----- ..."
}
```

Python 校验流程：

1. 先读取 JWT header 中的 `kid`
2. 根据 `kid` 找到匹配公钥
3. 用该公钥和 `RS256` 校验签名
4. 再校验 `iss`、`type`、`uid` 等业务字段

如果 `kid` 不存在或未知，应返回：

- HTTP `401`
- `code=40102`
- `errorCode=INVALID_TOKEN`

## 6. 公钥分发方案

建议分两个阶段：

### 阶段 A：配置分发

适合当前项目阶段，实施成本最低。

做法：

- Java 和 Python 都从环境变量或配置中心读取一组公钥
- Java 额外读取一把激活私钥
- 部署时统一更新配置

优点：

- 实现简单
- 不引入额外网络依赖

缺点：

- 公钥更新依赖配置发布
- 轮换自动化程度有限

### 阶段 B：JWKS 分发

更适合生产成熟阶段。

做法：

- Java 暴露只读 JWKS 端点，例如 `GET /.well-known/jwks.json`
- Python 和网关缓存 JWKS，并定期刷新

优点：

- 轮换更自然
- 更适合多服务和网关消费

缺点：

- 要增加缓存、刷新、失败回退策略
- 运维复杂度更高

结合当前项目阶段，建议：

- 第一阶段先实现“配置分发 + `kid`”
- 第二阶段再升级到 JWKS

## 7. 密钥轮换流程

### 7.1 轮换前提

必须先支持：

- token header 中带 `kid`
- 校验方支持多把公钥并存

否则不要进入轮换。

### 7.2 标准轮换步骤

以从 `2026-rot-a` 轮换到 `2026-rot-b` 为例：

1. 生成新密钥对 `2026-rot-b`
2. 将新公钥发布到 Java、Python、网关配置中
3. 保留旧公钥 `2026-rot-a`
4. 将 Java 的 `jwt.active-kid` 切换为 `2026-rot-b`
5. 新签发 token 开始使用 `2026-rot-b`
6. 等待旧 token 自然过期
7. 确认系统中已无 `2026-rot-a` 存量 token 依赖
8. 下线旧公钥 `2026-rot-a`

### 7.3 最短保留窗口

旧公钥最短保留时间应至少覆盖：

- `refresh token` 最大有效期
- 再加一段部署传播缓冲时间

以当前配置为例：

- access token：1 小时
- refresh token：7 天

因此旧公钥建议至少保留：

- `7 天 + 配置传播缓冲`

否则会出现旧 refresh token 无法再换新 access token 的问题。

## 8. refresh token 与轮换关系

在未实现 refresh token 轮换前，需要特别注意：

- refresh token 本身也是 JWT
- refresh token 也会携带 `kid`
- refresh token 校验时同样依赖旧公钥可用

所以当前阶段：

- 不能在切换激活私钥后立即移除旧公钥
- 必须等待旧 refresh token 彻底自然过期

后续如果引入 refresh token 轮换与会话表，可以缩短旧公钥保留窗口。

## 9. 失败场景与错误语义

建议统一这些错误行为：

- 缺少 `kid`：`401 / INVALID_TOKEN`
- `kid` 未知：`401 / INVALID_TOKEN`
- 签名校验失败：`401 / INVALID_TOKEN`
- token 过期：`401 / INVALID_TOKEN`
- issuer 不匹配：`401 / INVALID_TOKEN`
- token 类型错误：`401 / INVALID_TOKEN_TYPE`

这样前端与日志层面不需要为密钥轮换引入额外错误分支。

## 10. 配置与实现建议

### 10.1 Java 实现建议

建议新增一个密钥管理抽象，例如：

- `JwtSigningKeyProvider`
- `JwtVerificationKeyProvider`

职责：

- 根据 `activeKid` 提供当前签发私钥
- 根据 `kid` 返回对应公钥
- 支持从 PEM 或配置中心加载

`JwtTokenProvider` 需要调整为：

- 签发时在 header 写入 `kid`
- 校验时按 `kid` 选择公钥
- 默认拒绝无 `kid` 或未知 `kid` 的 token

### 10.2 Python 实现建议

建议把 `app/auth.py` 中当前的单密钥逻辑升级为：

- 先读取 unverified header
- 提取 `kid`
- 在 `jwt_public_keys` 映射中查找公钥
- 使用选中的公钥执行 `jwt.decode(...)`

同时保留当前：

- `issuer` 校验
- `type` 校验
- `uid` 必填校验

### 10.3 配置命名建议

建议未来统一为：

Java：

- `jwt.algorithm=RS256`
- `jwt.issuer=...`
- `jwt.active-kid=...`
- `jwt.private-key-pem=...`
- `jwt.public-keys-json=...`

Python：

- `ROVER_JWT_ALGORITHM=RS256`
- `ROVER_JWT_ISSUER=...`
- `ROVER_JWT_PUBLIC_KEYS_JSON=...`

如果仍保留对称签名作为过渡，还可以增加：

- `jwt.mode=hmac|rsa`

用于灰度迁移。

## 11. 分阶段落地建议

### 第一阶段：设计完成

- 明确 `RS256 + kid + 多公钥校验` 为目标方案
- 文档固定密钥轮换流程和保留窗口

### 第二阶段：代码支持双模式

- Java 支持 `HS256` 与 `RS256`
- Python 支持 `HS256` 与 `RS256`
- 增加 `kid` 解析与多公钥校验

当前代码状态：

- 这一阶段已完成
- 默认配置仍保持 `HS256`
- 下一步是准备并执行首次 `RS256` 切换

### 第三阶段：切换到 RSA

- 生产环境先发布公钥配置
- 将 Java 签发切换到 `RS256`
- 保留对旧模式兼容的短暂窗口

实施参考：

- [jwt-rs256-cutover.md](/mnt/disk2/pixels-rover/docs/jwt-rs256-cutover.md:1)

### 第四阶段：启用轮换

- 引入第二把 RSA 密钥
- 验证轮换流程
- 形成标准运行手册

## 12. 当前结论

对于 Pixels Rover，下一代生产级 JWT 方案建议明确为：

- 算法：`RS256`
- header：强制包含 `kid`
- Java：私钥签发
- Python / 网关：公钥校验
- 分发：先配置分发，后 JWKS
- 轮换：多公钥并存，等待旧 refresh token 过期后移除旧公钥

这套方案能够在不改变前端 Bearer 使用方式的前提下，把当前“共享对称密钥”的风险收敛到更适合工业生产的水平。
