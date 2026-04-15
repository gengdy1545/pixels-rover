# Pixels Rover 预发环境 RS256 切换与密钥轮换演练 Runbook

本文档用于指导 Pixels Rover 在预发环境完成一次完整的：

- 首次 `RS256` 切换
- `kid` 生效验证
- 多公钥并存验证
- 密钥轮换演练
- 回滚验证

目标不是上线，而是在预发把整条流程跑通。

## 1. 演练目标

本次演练需要验证：

1. Java `auth-service` 能以 `RS256` 签发 access token 和 refresh token
2. Python `analysis-service` 能根据 `kid` 校验 token
3. 前端登录、刷新 token、调用分析接口不受影响
4. 新旧公钥可并存校验
5. 切换 `active-kid` 后新 token 使用新密钥签发
6. 旧 token 在旧公钥保留期内仍可用
7. 回滚到旧 `kid` 或旧配置时系统可恢复

## 2. 演练前准备

### 2.1 代码前提

确认预发环境部署的版本已经包含：

- Java `auth-service` 的 `HS256/RS256 + kid` 支持
- Python `analysis-service` 的 `HS256/RS256 + kid` 支持
- `GET /api/v1/auth/jwks`
- `scripts/generate-jwt-rsa-keys.sh`

### 2.2 环境前提

确认预发环境具备：

- 可单独更新 Java 配置
- 可单独更新 Python 配置
- 可查看 Java 和 Python 日志
- 可通过前端完成登录、刷新 token 和分析请求

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

1. 登录一次，保存当前 access token 和 refresh token
2. 访问 `GET /api/v1/auth/user-info`
3. 访问一个 Python 受保护接口，例如：
   - `GET /api/v1/backends`
4. 执行一次 refresh token
5. 记录当前 token header 中的：
   - `alg`
   - `kid`
6. 记录 Java 与 Python 日志中的 `requestId`

预期：

- 当前链路全部成功
- 若环境仍是 `HS256`，可作为切换前对照组

### 阶段 B：生成两套 RSA 密钥

生成两套密钥：

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
- `preprod-rsa-a-public-keys.json`
- `preprod-rsa-b-private.pem`
- `preprod-rsa-b-public.pem`
- `preprod-rsa-b-public-keys.json`

### 阶段 C：先发布公钥，不切签发

先把两把公钥都发布给校验方：

- Python `analysis-service`
- 如有网关，也同步发布

建议 Python 配置：

```dotenv
ROVER_JWT_ALGORITHM=RS256
ROVER_JWT_ACTIVE_KID=preprod-rsa-a
ROVER_JWT_PUBLIC_KEYS_PATH=/secure/preprod/jwt-keys/all-public-keys.json
```

其中 `all-public-keys.json` 至少包含：

```json
{
  "preprod-rsa-a": "-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----",
  "preprod-rsa-b": "-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----"
}
```

注意：

- 这一步先只更新公钥配置，不切 Java 签发算法
- 发布后确认 Python 服务可正常启动

### 阶段 D：Java 首次切换到 RS256

将 Java `auth-service` 切换为：

```properties
jwt.algorithm=RS256
jwt.active-kid=preprod-rsa-a
jwt.private-key-path=/secure/preprod/jwt-keys/preprod-rsa-a-private.pem
jwt.public-key-path=/secure/preprod/jwt-keys/preprod-rsa-a-public.pem
jwt.public-keys-path=/secure/preprod/jwt-keys/all-public-keys.json
```

发布 Java 后执行：

1. 登录获取新 token
2. 解码 token header
3. 确认：
   - `alg=RS256`
   - `kid=preprod-rsa-a`
4. 用该 token 访问：
   - `GET /api/v1/auth/user-info`
   - `GET /api/v1/backends`
   - `POST /api/v1/analysis`
5. 执行 refresh token
6. 确认刷新出的 access token 仍为：
   - `alg=RS256`
   - `kid=preprod-rsa-a`

### 阶段 E：验证多公钥并存

保持 Python 与 Java 都持有：

- `preprod-rsa-a`
- `preprod-rsa-b`

但此时 Java 仍用：

- `active-kid=preprod-rsa-a`

验证：

1. 使用阶段 D 中签发的 token 调用接口
2. 确认旧 token 继续可用
3. 访问 `GET /api/v1/auth/jwks`
4. 确认返回的 JWK 集中包含当前可公开的 RSA key 集合

### 阶段 F：模拟轮换切到新 kid

将 Java 切换为：

```properties
jwt.algorithm=RS256
jwt.active-kid=preprod-rsa-b
jwt.private-key-path=/secure/preprod/jwt-keys/preprod-rsa-b-private.pem
jwt.public-key-path=/secure/preprod/jwt-keys/preprod-rsa-b-public.pem
jwt.public-keys-path=/secure/preprod/jwt-keys/all-public-keys.json
```

发布后执行：

1. 重新登录获取新 token
2. 确认新 token：
   - `alg=RS256`
   - `kid=preprod-rsa-b`
3. 用新 token 访问 Java 和 Python 受保护接口
4. 再使用阶段 D 里签发的旧 token 调用 Python 接口

预期：

- 新 token 正常通过
- 旧 token 也仍然通过

这一步就是“多公钥并存 + 切 active-kid”的关键验证。

### 阶段 G：验证 refresh token 兼容

在切到 `preprod-rsa-b` 后：

1. 使用阶段 D 获取的旧 refresh token 调用 `/api/v1/auth/refresh`
2. 确认 refresh 仍成功
3. 确认新 access token 由当前激活 `kid=preprod-rsa-b` 签发

这一步非常关键，因为它验证了：

- 旧 refresh token 依赖旧公钥仍可被识别
- 新 access token 已被新私钥签发

## 5. 演练完成条件

只有同时满足下面条件，才算演练成功：

- 首次 `RS256` 切换成功
- `kid` 正常写入 token header
- Python 能根据 `kid` 校验 token
- 新旧 token 能在并存窗口内同时被接受
- refresh token 兼容验证成功
- `jwks` 端点可用
- 回滚方案已验证

## 6. 回滚步骤

如果任一步失败，按下面顺序回滚：

1. Java `auth-service`
   - 恢复到上一个稳定配置
   - 恢复旧 `jwt.algorithm`
   - 恢复旧 `active-kid` 或旧 `HS256` 配置
2. Python `analysis-service`
   - 保留多公钥配置，不需要立即删
   - 确认仍能校验旧 token
3. 前端
   - 一般无需改动
   - 如用户本地 token 已不兼容，可重新登录

回滚后重新验证：

- 登录
- user-info
- refresh token
- Python 受保护接口

## 7. 观察项清单

演练期间建议记录：

- Java 登录接口日志
- Java refresh 接口日志
- Python 鉴权失败日志
- `requestId`
- token 的 `alg` / `kid`
- 切换前后成功率

## 8. 演练后的决策

演练结束后应明确给出结论：

### 结果 A：通过

说明：

- 预发环境可支撑 `RS256 + kid`
- 可以进入生产切换审批

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

- 密钥生成脚本：[generate-jwt-rsa-keys.sh](/mnt/disk2/pixels-rover/scripts/generate-jwt-rsa-keys.sh:1)
- 多公钥合并脚本：[merge-jwt-public-keys.sh](/mnt/disk2/pixels-rover/scripts/merge-jwt-public-keys.sh:1)
- 自动化演练脚本：[preprod-rotation-drill.sh](/mnt/disk2/pixels-rover/scripts/preprod-rotation-drill.sh:1)

自动化演练脚本支持按阶段执行：

```bash
# Run all phases
bash scripts/preprod-rotation-drill.sh

# Run a specific phase
bash scripts/preprod-rotation-drill.sh B
```
