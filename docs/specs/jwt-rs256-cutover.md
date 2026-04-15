# Pixels Rover JWT RS256 切换步骤

本文档描述如何把当前默认的 `HS256` JWT 签名切换到 `RS256 + kid`。

## 1. 前提

当前代码已具备这些能力：

- Java `auth-service` 支持 `HS256` / `RS256` 双模式签发与校验
- Python `analysis-service` 支持 `HS256` / `RS256` 双模式校验
- JWT header 已支持 `kid`
- Python 已支持基于 `kid` 选择 RSA 公钥

如果这些还未部署到目标环境，不要开始切换。

## 2. 生成第一套 RSA 密钥

在仓库根目录执行：

```bash
bash scripts/generate-jwt-rsa-keys.sh
```

默认输出到：

```text
.tmp/jwt-keys/
```

也可以自定义输出目录和 `kid`：

```bash
bash scripts/generate-jwt-rsa-keys.sh /secure/path/jwt-keys 2026-rot-a
```

脚本会生成：

- 私钥 PEM
- 公钥 PEM
- `public-keys.json`
- 配置片段示例

## 3. 发布公钥

先不要切换 Java 的签发算法，先把新公钥发布到校验方。

### 3.1 Python `analysis-service`

在 `.env` 中设置：

```dotenv
ROVER_JWT_ALGORITHM=RS256
ROVER_JWT_ACTIVE_KID=2026-rot-a
ROVER_JWT_PUBLIC_KEYS_JSON={"2026-rot-a":"-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----"}
```

注意：

- 公钥要保留 PEM 文本
- JSON 里的换行要转义为 `\\n`
- 这一阶段 Python 具备 RSA 校验能力即可

更推荐的生产方式是使用文件路径配置：

```dotenv
ROVER_JWT_ALGORITHM=RS256
ROVER_JWT_ACTIVE_KID=2026-rot-a
ROVER_JWT_PUBLIC_KEY_PATH=/secure/path/2026-rot-a-public.pem
ROVER_JWT_PUBLIC_KEYS_PATH=/secure/path/public-keys.json
```

## 4. 切换 Java `auth-service` 到 RS256

在 Java 配置中设置：

```properties
jwt.algorithm=RS256
jwt.active-kid=2026-rot-a
jwt.private-key-pem=-----BEGIN PRIVATE KEY-----...
jwt.public-key-pem=-----BEGIN PUBLIC KEY-----...
jwt.public-keys-json={"2026-rot-a":"-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----"}
```

建议：

- 私钥从密钥管理系统注入
- 不要把真实私钥直接提交到仓库
- 更推荐使用 `jwt.private-key-path`、`jwt.public-key-path`、`jwt.public-keys-path`

## 4.1 公钥发布端点

Java `auth-service` 现在已提供只读公钥端点：

```http
GET /api/v1/auth/jwks
```

用途：

- 未来供网关或其他服务消费公钥
- 为后续升级到标准 `JWKS` 流程做准备

当前它返回统一 `ApiResponse` 包裹的 JWK 集合。

## 5. 验证切换结果

至少做这几项验证：

1. 登录成功，Java 返回的 token header 中 `alg=RS256`
2. token header 中存在 `kid`
3. 前端继续能正常携带 Bearer token 访问 Python 接口
4. Python 能成功校验新的 RSA token
5. refresh token 仍可正常换新 access token

## 6. 正式轮换前不要做的事

在还没形成“多公钥并存 + refresh token 生命周期治理”之前，不要：

- 立即删除旧公钥
- 多次快速切换 `active-kid`
- 在没有联调验证的情况下直接生产切换

## 7. 下一步

完成首次 `RS256` 切换后，再进入：

- 第二把密钥接入
- 多公钥并存验证
- 真正的轮换演练

预发演练步骤详见：

- [jwt-preprod-rotation-drill.md](/mnt/disk2/pixels-rover/docs/jwt-preprod-rotation-drill.md:1)
