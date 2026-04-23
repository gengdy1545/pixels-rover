# JWT Key Provisioning Runbook（生产密钥交付与部署）

> 本文件是**运维可执行 runbook**——描述 Pixels Rover 在生产环境如何生成、交付、部署 `auth-service` 使用的 RS256 JWT 密钥对。设计沿革与密钥模型定义见 [`../design/jwt-rotation.md`](../design/jwt-rotation.md)；与 dev 文档的硬约束对齐见 [`../development/backend.md §13.1`](../development/backend.md)。
>
> **适用边界**：本文件只覆盖**生产环境**的密钥 provisioning。dev 环境（本地 `docker compose up`）继续使用 `docker-compose.yml` 中的 `jwt-keygen` 一次性初始化容器，不走本 runbook。

## 1. 架构前提（复核）

在按本 runbook 操作之前，确认下列前提均成立——任一不成立时先回到对应文档补齐：

- `auth-service` 在生产环境**只部署单实例**（`backend.md §13.1` 硬规则）。该假设让本 runbook 可以用"挂载到单一容器"的最简形态交付密钥；若未来横向扩容到多实例，**必须**先回 `../design/jwt-rotation.md §6` 重新选择密钥分发方案再回本 runbook 更新流程。
- `JWT_ALGORITHM = RS256`。HS256 不走本流程（HS256 是单 secret 轮换，运维意义与本 runbook 不同）。
- `gateway` 与 `assistant-service` **不接触** JWT 密钥——本 runbook 的所有密钥材料只交付到 `auth-service` 容器，其他容器**不得**挂载 `jwt-keys` 卷（`docker-compose.yml` 里该卷仅 bind 到 `auth-service` 即为硬边界）。

## 2. 密钥材料结构

交付到 `auth-service` 容器的密钥目录（容器内路径 `/jwt-keys/`）包含：

| 文件 | 格式 | 用途 | 必需？ |
|---|---|---|---|
| `<ACTIVE_KID>-private.pem` | PKCS#8 或 PKCS#1 PEM | 当前激活的签发私钥 | 是 |
| `<ACTIVE_KID>-public.pem` | PEM | 与上对应的公钥（`auth-service` 自校验用） | 是 |
| `<RETIRED_KID>-public.pem` | PEM | 上一轮次未完全过期的旧公钥（轮换期保留） | 轮换期必需，否则可选 |

命名规则硬约束（与 `backend.md §13.1` 的 `JWT_PUBLIC_KEYS_DIRECTORY` 枚举约定对齐）：

- 每个 `<kid>` 必须成对存在 `<kid>-private.pem` + `<kid>-public.pem`，或仅 `<kid>-public.pem`（旧 kid，已下线私钥）。
- 文件名的 `<kid>` 部分**必须与**被它签发的 JWT header `kid` 字段字面一致。
- ❌ **禁止**出现 `all-public-keys.json` / `jwks.json` / `<kid>-public-keys.json` 等"合并产物"——这些是 JWKS 下线前的旧形态，见 `../design/jwt-rotation.md §6.B`。

## 3. 密钥生成（本地受控环境执行）

**不要**在生产服务器上直接生成密钥——生成环境应是个**受控的本地工作站**（个人开发机 / 公司发放的受控 ops 机器），与生产网络完全隔离。

### 3.1 生成一个新 kid 的密钥对

推荐使用仓库提供的脚本 `scripts/generate-jwt-rsa-keys.sh`（dev 容器 `jwt-keygen` 也使用同一脚本，但本节在受控环境直接执行）：

```bash
# 在一个受控的、联网最小化的 shell 里执行
mkdir -p /tmp/pixels-rover-keys-$(date +%Y%m%d)
cd /tmp/pixels-rover-keys-$(date +%Y%m%d)

# <KID> 命名建议：<year>-<purpose>-<rev>，例如 2026-prod-a
./scripts/generate-jwt-rsa-keys.sh "$PWD" "2026-prod-a"

ls -l
# 预期输出：
#   2026-prod-a-private.pem  (0600 权限)
#   2026-prod-a-public.pem   (0644 权限)
```

若当前工作站未安装 openssl 或脚本不可用，等价手工命令：

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out 2026-prod-a-private.pem
openssl rsa -pubout -in 2026-prod-a-private.pem -out 2026-prod-a-public.pem
chmod 600 2026-prod-a-private.pem
chmod 644 2026-prod-a-public.pem
```

**密钥参数基线**：RSA 2048 位；不使用 passphrase 加密私钥（运行时需要非交互加载）；不生成 key id 之外的元数据文件。

### 3.2 命名与 kid 选择

- `<KID>` 为短字符串，**建议 ≤ 32 字符**，`[a-z0-9\-]` 字符集；不含路径分隔符、不含空白。
- 新启一个 kid 的典型场景：首次上线（`2026-prod-a`）；计划性轮换（`2026-prod-b`）；应急轮换（`2026-incident-<date>`）。
- 同一时间同一环境**激活的 kid 只能有一个**（即 `JWT_ACTIVE_KID` 指向的那个）；其他 kid 以公钥形式保留用于校验存量 token。

## 4. 密钥交付（受控环境 → 生产节点）

### 4.1 交付原则

- **不通过 git 提交**任何私钥 / 公钥文件（仓库 `.gitignore` 必须包含 `*.pem`）；
- **不通过 IM / 邮件**发送私钥文件；
- **不通过** CI artifact 携带私钥（构建镜像里也不得 bake 私钥）；
- 通过受控通道（SSH `scp`、公司制品库加密通道、物理移动介质）把**整个密钥目录**一次性传到生产节点的运维用户主目录；
- 生产节点落盘后**立即** `chmod 700` 目录 + `chmod 600` 私钥；
- 私钥 / 公钥文件的**副本数**在整个 provisioning 过程中 ≤ 3（受控工作站本地 1 + 生产节点 1 + 离线冷备 1），**不得**在多台机器间反复传阅。

### 4.2 生产节点的 bind-mount 布局

在生产节点上选定一个**只对 docker daemon + 运维账号可读**的目录作为卷源（例如 `/opt/pixels-rover/jwt-keys/`），将上一节交付的所有 `.pem` 文件放入该目录。

`docker-compose.yml` 在生产上**不使用** dev 默认的 `jwt-keys` named volume + `jwt-keygen` init 容器组合；改为 bind mount 宿主目录到 `auth-service` 容器的 `/jwt-keys`：

```yaml
# docker-compose.prod.yml 或等价生产编排
services:
  auth-service:
    volumes:
      - /opt/pixels-rover/jwt-keys:/jwt-keys:ro
    environment:
      JWT_ALGORITHM: RS256
      JWT_ACTIVE_KID: 2026-prod-a
      JWT_PRIVATE_KEY_PATH: /jwt-keys/2026-prod-a-private.pem
      JWT_PUBLIC_KEY_PATH: /jwt-keys/2026-prod-a-public.pem
      JWT_PUBLIC_KEYS_DIRECTORY: /jwt-keys
  # 注意：生产编排里 **必须移除** dev 默认的 jwt-keygen service。保留该 init 容器 =
  # 让生产自动生成密钥，违反受控 provisioning 原则。
```

硬约束：

- ❌ **禁止**在生产编排里保留 `jwt-keygen` 容器 —— 即便它只在 volume 为空时跑一次，也会在运维人员第一次手滑删除卷之后自动"重新生成"一套全新密钥，瞬间把所有现存 JWT 打成无效。
- ❌ **禁止**把宿主目录挂载成 `:rw`（读写）到 auth-service 容器 —— auth-service 进程对密钥目录只有读需求。
- ❌ **禁止**把同一 bind mount 同时挂载到 `gateway` / `assistant-service` 等其他容器（见 §1 架构前提）。

### 4.3 启动期自检

auth-service 启动时会按 `backend.md §13.1` 做以下硬校验——任一失败 **FATAL 退出**，不要"先忍一下"启动：

1. `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` 文件存在且可读；
2. 两个文件构成合法密钥对（启动期做一次 sign → verify 自测）；
3. `JWT_PUBLIC_KEYS_DIRECTORY` 下所有 `*-public.pem` 可枚举、可解析；
4. `JWT_ACTIVE_KID` 对应的公私钥对在上述目录中确实存在；
5. `JWT_SECRET` **未**在环境中设置（RS256 部署下 HS256 变量出现即视为配置漂移，FATAL）。

启动成功后日志应打印（**不**打印密钥内容，只打印元信息）：

```
[auth-service] JWT config: algorithm=RS256 activeKid=2026-prod-a verifiablePublicKeys=[2026-prod-a] keyDir=/jwt-keys
```

如果日志中出现额外的 kid（例如你还没放进去的 `2026-prod-b`），说明密钥目录污染，立即停服排查。

## 5. 轮换（计划性）

计划性轮换的密码学原理与标准步骤见 [`../design/jwt-rotation.md §7`](../design/jwt-rotation.md)；本节只给运维动作序列，设计问题一律回去查那边。

演练环境的一次完整走通见 [`./jwt-rotation-drill.md`](./jwt-rotation-drill.md)，**生产第一次轮换前必须先完整演练一次**。

生产轮换动作（从 `2026-prod-a` 到 `2026-prod-b`）：

1. 在受控工作站按 §3 生成 `2026-prod-b` 密钥对；
2. 把新公私钥通过 §4.1 渠道交付到生产节点 `/opt/pixels-rover/jwt-keys/`；
3. **先不改 `JWT_ACTIVE_KID`**，只重启 auth-service——让它把新公钥加载进 `JWT_PUBLIC_KEYS_DIRECTORY` 的枚举结果（校验侧先认，签发侧还是旧 kid）；
4. 观察 §6 清单中 auth-service / gateway 日志至少 15 分钟，无异常；
5. 修改 compose 环境变量 `JWT_ACTIVE_KID=2026-prod-b`、`JWT_PRIVATE_KEY_PATH=/jwt-keys/2026-prod-b-private.pem`、`JWT_PUBLIC_KEY_PATH=/jwt-keys/2026-prod-b-public.pem`；
6. 重启 auth-service；新签发的 JWT header `kid=2026-prod-b`；
7. 等至少 refresh token 的最大有效期（默认 7 天）+ 配置传播缓冲（≥ 1 天）后，才能从生产节点删除 `2026-prod-a-public.pem`；**不要**急着清理旧公钥；
8. 所有旧 kid 公钥下线后，重启 auth-service 确认枚举里只剩当前 kid。

**不得在轮换窗口执行的动作**：

- ❌ 同时动 `JWT_ALGORITHM`（例如轮换 + 切算法同 PR）；
- ❌ 同时动 `INTERNAL_INTROSPECTION_SECRET` / `INTERNAL_GATEWAY_ADMIN_SECRET`；
- ❌ 在 §7 步骤 7 未到期之前删除旧私钥以外的任何文件。

## 6. 故障兜底（应急轮换）

当怀疑私钥泄漏时按以下序列：

1. 在受控工作站生成一个新的 `<incident-kid>` 密钥对（命名例：`2026-incident-20260401`）；
2. 通过 §4 渠道交付；
3. **同时**改 `JWT_ACTIVE_KID` 指向新 kid 并**物理删除**旧私钥文件（只留旧公钥以兼容存量 token，或连公钥一并删除走"用户强制重登"路径）；
4. **同一窗口内**通过 [`../development/gateway.md §5.3`](../development/gateway.md) 的 `POST /gateway/internal/invalidate_session` 触发"按 `userId`" 的批量失效（或走更激进的按全量 tokenHash 遍历；由于 `lua_shared_dict` 是 per-instance，invalidate 只影响当前 gateway 实例——这里再次用到 §1 的"单实例假设"）；
5. 观察 30 分钟内无异常签发 / 异常 introspect 失败率飙升（具体观察项见 [`./jwt-rotation-drill.md §7`](./jwt-rotation-drill.md)）；
6. 事后复盘：事件时间线、密钥泄漏渠道、是否需要加固 §4 的交付链路。

"激进清理旧公钥"是**以强制全体用户重登为代价**换取"旧 token 立即失效"——只在真实泄漏时使用；计划性轮换场景不得走这条路径。

## 7. 安全检查清单（每次 provisioning / 轮换之后跑一遍）

- [ ] 生产节点 `/opt/pixels-rover/jwt-keys/` 目录权限 = `700`，owner = 运维账号；
- [ ] 目录内每个 `*-private.pem` 权限 = `600`，owner = 运维账号；
- [ ] 目录内**没有** `*.json` / `all-public-keys*` / `jwks*` 类合并产物（若有，立即删除并查 `../design/jwt-rotation.md §6.B` 复活清单）；
- [ ] `docker-compose.yml` / `docker-compose.prod.yml` 中**无** `jwt-keygen` 服务条目；
- [ ] `auth-service` 容器启动日志打印出的 `activeKid` 与环境变量 `JWT_ACTIVE_KID` 一致；
- [ ] `auth-service` 容器启动日志**没有**打印任何密钥材料字节（只应看到 kid 列表 / 文件路径等元信息）；
- [ ] 受控工作站上已完成密钥生成的临时目录已清理（`rm -rf /tmp/pixels-rover-keys-*` 或等价）；
- [ ] git status 在受控工作站上干净（未意外 track 任何 `.pem`）；
- [ ] `.gitignore` 包含 `*.pem` / `jwt-keys/` 的根级忽略。

## 8. 与其他文档的耦合

- [`../design/jwt-rotation.md`](../design/jwt-rotation.md)：设计沿革与密钥模型；本 runbook 对其为"实现投影"，设计问题以那边为准。
- [`./jwt-rotation-drill.md`](./jwt-rotation-drill.md)：演练手册；生产第一次走 §5 / §6 之前**必须**先完整走一遍演练。
- [`../development/backend.md §13.1`](../development/backend.md)：启动期硬校验规则；本 runbook 交付的密钥结构必须满足那里的所有约束。
- [`../development/backend.md §2.2`](../development/backend.md)：横向调用边界；应急轮换走 gateway `invalidate_session` 是当前阶段唯一允许的反向调用，与该节的特许条目对齐。
- [`./observability-roadmap.md`](./observability-roadmap.md)：轮换期观测点在阶段 B（管道引入）之后会入可视化面板；当前阶段只靠 `docker logs`。
