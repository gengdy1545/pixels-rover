# Gateway 开发指南

本文档固定 Pixels Rover **API 网关** 的技术选型、部署形态、职责边界与开发纪律。

- 适用范围：仓库中 `gateway/` 目录（APISIX 网关）。
- 设计前提：
  - 产品长期只保留**单 Web 前端**；
  - gateway 是**所有流量的唯一入口**，同时承担 **API 路由 + Web 静态分发** 双职责；
  - 后端服务均走"插件式"接入，对外暴露 REST/SSE API 即可，不直接被浏览器访问。
- 文档目的：让任何新同学在不读历史对话的情况下，也能按一致的方式改网关、接新服务、配策略；同时把已经做过的设计决策锁死，避免回归到"etcd + Admin API + shell bootstrap"这种重装形态。
- 以代码事实为准：若代码与本文档出现漂移，优先修正代码或及时更新本文档。

---

## 1. 技术选型与部署形态

### 1.1 选型结论

- **网关实现：Apache APISIX 3.9.1（Debian 镜像）**
- **部署形态：Standalone YAML 模式**（`deployment.role: data_plane` + `config_provider: yaml`）
  - 不使用 etcd
  - 不使用 Admin API 热更新
  - 不使用 APISIX Dashboard
  - 所有 routes / upstreams / plugins 通过单一 `apisix.yaml` 文件声明，随代码一起进 git
- **自研插件：`gateway-auth`**（`gateway/custom/apisix/plugins/gateway-auth.lua`），承担认证、CSRF、身份头注入、request-id 三合一

### 1.2 为什么是 Standalone YAML 而不是 Traditional + etcd

| 维度 | Traditional + etcd | Standalone YAML（采用） |
|---|---|---|
| 多实例集群同步 | 需要 | 不需要 |
| 运行时热改路由 | 需要 | 不需要（所有变更走 PR） |
| 依赖组件 | etcd + bootstrap 容器 | 无 |
| 配置 review | JSON + shell `curl PUT` | 一份 YAML，PR diff |
| 失败模式 | bootstrap 容器挂 → 路由表空 | YAML 解析失败 → 启动即拒绝 |

本项目**没有任何需要 Traditional 模式的场景**：网关单实例、路由表变更频率低、没有"运行时灰度改路由"的需求。Standalone YAML 在本项目是严格优势。

**触发重新评估的信号**（出现任一条再回来重开选型讨论，不要"为了未来"提前引入 etcd）：

- **多实例**：gateway 需要横向扩展到 ≥ 2 实例，且各实例的 `gateway-auth` introspect 缓存必须跨实例失效；
- **运行时灰度**：产品形态变成"需要 A/B 测试级别的实时路由切换"；
- **跨团队发路由**：多个团队需要独立发自己的路由变更，走 PR 合并成为事实上的瓶颈；
- **配置体积**：`apisix.yaml` 超过 ~2000 行、单次 PR 难以 review。

### 1.3 目录结构

```text
gateway/
├── Dockerfile
├── entrypoint.sh             读取环境变量，渲染 config.yaml 与 apisix.yaml
├── config.yaml.template      APISIX 启动配置模板（data_plane + yaml）
├── apisix.yaml               路由/upstream/插件的唯一声明文件（随代码版本化）
└── custom/
    └── apisix/
        └── plugins/
            └── gateway-auth.lua    自研插件
```

**显式约束**：`gateway/` 下不允许再出现 `gateway/njs/`、`gateway/snippets/` 等空目录；不允许再出现 `bootstrap.sh` + etcd + Admin API 这一套重装组件。

---

## 2. Gateway 的长期职责边界

### 2.0 单实例部署假设（总纲）

本规范中**一切**涉及进程内共享状态的机制都**绑定当前项目的单实例部署假设**——即同一环境里 `gateway` 只部署 1 个 APISIX 实例（见 §1.2）。具体受该假设约束的内容包括：

- **`gateway-auth` 的 `lua_shared_dict gateway_auth_cache` 等三张 shared dict**（§5.3.2）：`per-nginx-process`，不跨实例。
- **`POST /gateway/internal/invalidate_session` 主动吹缓存**（§5.3）：只失效当前实例的 cache，不广播到其他实例。
- **`limit-count` 限流计数**（§6.5）：APISIX 默认存在 `lua_shared_dict`，单实例语义。
- **session 主动失效链路**：依赖 auth-service → gateway 反向调用直达同一台实例。

**硬规则**：以上任何一条的多实例支持，都会**结构性破坏**本文档当前设计的正当性（例如一旦 invalidate 只能失效 1/N 实例，`positive_cache_ttl=30s` 的安全性假设立刻瓦解）。任何"横向扩容到 ≥ 2 gateway 实例"的改动必须**先**回到 §1.2 "触发重新评估的信号" 重新做选型决策，**然后**才进入实现评估——而不是反过来。

当前阶段锁定单实例形态；本节上方 §1.2 的触发信号清单是退出该形态的**唯一**入口。

### 2.1 Gateway 应该做的事

- **统一入口**：所有浏览器流量都打到网关，后端服务不对外暴露端口。
- **Web 静态分发**：`/*` 兜底到 `frontend` upstream，长期形态，不规划独立 CDN。
- **API 路由**：按领域前缀（`/api/v1/auth/*`、`/api/v1/analysis*`、`/api/v1/conversations*`、`/api/v1/semantic*`、`/api/v1/analysis/backends*`）分发到后端。
- **认证（AuthN）**：通过 `gateway-auth` 插件调 auth-service 的 `/api/internal/auth/introspect` 校验 token。
- **CSRF 保护**：在需要保护的路由上执行 double-submit 校验。
- **身份头注入**：`X-Auth-User-Id` / `X-Auth-User-Email` / `X-Auth-Session-Id`，作为下游服务唯一的身份事实。
- **Request-Id 生成与透传**：所有请求补齐 `X-Request-Id`，贯穿日志链路。
- **路由级粗粒度授权**：`require_auth` 布尔；未来若引入角色，新增 `require_role`。
- **跨域（CORS）**：**唯一的** CORS 处理点；后端服务不再自行处理跨域。
- **限流 / 熔断 / 超时**：针对 upstream 配置通用策略，SSE / LLM 长连接单独豁免。
- **安全响应头下发**：**一层**下发 HSTS / CSP / X-Frame-Options / Referrer-Policy / Permissions-Policy / `X-Content-Type-Options`（见 §6.6），业务服务与前端容器不得重复下发同名响应头。
- **审计**：结构化日志与核心指标口径由 gateway 统一（见 §8），业务服务输出对齐字段名，便于跨层聚合。

### 2.2 Gateway 不应该做的事

以下内容属于"业务知识"，网关不懂也不该懂：

- **资源级授权**（例如"user X 能不能读 thread #789"） → 业务服务
- **业务数据校验**（字段合法性、业务规则） → 业务服务
- **用户身份真源**（user 表的所有权） → auth-service
- **角色/组的真源**（role 表、分组关系） → auth-service
- **token 签发与吊销** → auth-service
- **SQL 或 DSL 解析** → 业务服务

### 2.3 一条粗粒度判断规则

> **"能不能只看 HTTP 语义、身份头、路由配置就判断的问题，放在网关；必须看数据库里的业务字段才能回答的问题，放在业务服务。"**

### 2.4 Web 静态分发的分层

"Web 静态分发属于 gateway 职责"在本项目的**落地形态**是：**gateway 作为反向代理层把 `/*` 转发给 frontend upstream**，而 frontend upstream 是一个独立的前端容器（内部跑轻量 nginx serve 构建产物）。职责分层：

| 层 | 归属 | 做什么 |
|---|---|---|
| **接入层**（gateway） | `gateway/` | 域名接入、TLS、CORS、**安全响应头（§6.6）**、路由分发、`/*` 兜底到 frontend upstream |
| **静态分发层**（frontend container） | `frontend/` | 托管 Vite 构建产物、gzip/brotli 压缩、`index.html` 的 `Cache-Control: no-store`、静态资源的长缓存 |

**为什么保留两层而不合并到 gateway 一层**：

- 前端镜像可独立版本化、独立升级，不触发网关重启；
- 网关层是平台工程资产，前端层是产品研发资产，生命周期不同；
- 压缩/缓存/`index.html` 的处理对产品侧改动频繁，不应污染网关配置。

**落地硬规则**：

- frontend 容器在 `docker-compose.yml` 里**只 `expose`、不 `ports`**（与业务服务同一原则），浏览器永不直连。
- `index.html` 的 `Cache-Control: no-store` 配在前端容器的 `nginx.conf`，不配在 gateway。
- 安全响应头（CSP/HSTS 等，见 §6.6）由 gateway **一层下发**，前端容器**不重复**。
- **SPA 深链接 fallback（硬规则）**：前端容器的 `nginx.conf` 必须对 `/*` 非静态资源路径回退到 `index.html`——典型形态 `try_files $uri $uri/ /index.html;`。SPA 使用 HTML5 history routing 时，刷新深链接（如 `/reports/abc`）会把原始 URI 打到静态分发层，缺 fallback 会 404。该 fallback **配在 frontend 容器、不配在 gateway**（gateway 的 `/*` 只负责转发到 frontend upstream，不理解 SPA 路由形态）。**反例**：把 fallback 配在 gateway 侧（用 `proxy-rewrite` 把 404 改写为 `/index.html`），会让未来引入 SSR / SSG 时 gateway 层成为改造阻碍。

---

## 3. 权限分层归属（硬规则）

把"权限检查"拆成四层，归属固定。

| 层 | 问题 | gateway | auth-service | 业务服务 |
|---|---|:-:|:-:|:-:|
| A. 认证（token 签名/过期/撤销） | 你是谁？ | ✅ 执行 | ✅ 真源 | ❌ |
| B. 身份上下文 | 你是哪个用户 | ✅ 注入 | ✅ 真源 | ✅ 消费 |
| C1. 路由级"是否要登录" | 这个接口需不需要登录 | ✅ | ❌ | ❌ |
| C2. 路由级"需要哪个角色" | 这个接口需不需要 admin | ✅ 执行 | ✅ 真源 | ❌ |
| D. 资源级"你能不能操作这个资源" | user 42 能不能改 thread #789 | ❌ | ❌ | ✅ |

### 3.1 业务服务侧的硬规则

- ✅ **必须**：从 `X-Auth-User-Id` 头取用户身份，在所有业务查询里强制 `WHERE owner_user_id = :userId`（或等价的 service 层判断）。
- ❌ **禁止**：重新校验 JWT、直接读 `pixels_auth.user` 表、自己调 `introspect`、返回 AuthN 级错误（401 这种判断根本打不到业务服务）。
- ❌ **禁止**：依赖客户端传来的 `userId` 字段——只认 `X-Auth-User-Id` 头。

### 3.2 Gateway 侧的硬规则

- ✅ **必须**：在身份注入前清空请求里**所有**以 `X-Auth-` / `x-auth-` 为前缀的头（防止客户端伪造），然后只填 introspect 结果里的字段。
- ✅ **必须**：清空实现走**前缀扫描**（遍历 `ngx.req.get_headers()` 的 key，对所有 `X-Auth-` / `x-auth-` 前缀的头执行 `ngx.req.clear_header`），**不得**硬枚举已知的 `X-Auth-User-Id` / `X-Auth-User-Email` / `X-Auth-Session-Id` 三个头——枚举形态会在未来新增 `X-Auth-<Attr>` 时因"没被枚举到"而漏清空，形成客户端可伪造的漏洞。PR review 只要看到"枚举式 clear"一律拒绝合并。
- ❌ **禁止**：在网关插件里写任何业务规则（例如"assistant-service 的 thread ownership 检查"）——一旦出现，网关就和业务 schema 耦合了。
- ❌ **禁止**：Gateway 拿着 `X-Auth-*` 头查业务库——违反职责边界。

### 3.3 auth-service 侧的硬规则

- ✅ **必须**：`introspect` 响应稳定包含 `active` / `userId` / `email` / `sessionId`；未来扩展 `roles` / `tenantId` 等字段要做向后兼容。
- ❌ **禁止**：import 任何业务领域概念（conversation / analysis / backend / schema）。
- ❌ **禁止**：为业务服务提供"用户是否有权限 X"这类语义检查——auth-service 只管身份，不管业务。

---

## 4. 健康检查规范

### 4.1 两条健康路由，语义分开

- **`/gateway/live`（Liveness）**
  - **纯本地**，不过任何 upstream。
  - 直接返回静态 200 / 轻量 JSON。
  - **用途**：Docker healthcheck、K8s livenessProbe。
  - 语义："网关进程自己还在响应"。

- **`/gateway/ready`（Readiness，系统级聚合信号）**
  - 由这个路由主动去探每个已注册业务服务的 `/health`。
  - **用途**：负载均衡摘流、K8s readinessProbe、`docker compose up` 冒烟判据（由 `scripts/smoke.sh` 作为系统级就绪信号轮询）。
  - 语义："上游就绪 = 可以对外服务"。
  - **绝对不能作为容器重启判据**。

  **实现形态（独立插件 + 声明式 probe 清单）**：聚合逻辑落成独立 APISIX 自定义插件 [`gateway-ready`](../../gateway/custom/apisix/plugins/gateway-ready.lua)，挂在 `/gateway/ready` 这一条路由上。插件在 `access` 阶段用 `ngx.location.capture_multi` 并行 sub-request 到每条内部 location（每条 internal location `proxy_pass` 到一个 upstream 的 `/health`），汇总后直接写响应体并短路 upstream。

  probe 清单作为**插件实例配置**声明在路由上，不是硬编码到插件里：

  ```yaml
  # apisix.yaml 片段（Standalone YAML 模式）
  routes:
    - uri: /gateway/ready
      methods: [GET]
      plugins:
        gateway-ready:
          probes:
            - { name: "auth-service",      uri: "/__ready_probe/auth",      timeout_ms: 1000 }
            - { name: "assistant-service", uri: "/__ready_probe/assistant", timeout_ms: 1000 }
          total_timeout_ms: 2000
      upstream:
        # 占位 upstream，插件在 access 阶段已 ngx.exit，绝不会被触达
        nodes: { "127.0.0.1:65535": 1 }
        type: roundrobin
  ```

  聚合规则：任一 probe 非 200 → 整体 503；全部 200 → 200。响应体遵循 [`./backend.md §6.0`](./backend.md) 信封，`details.components[]`（失败）或 `data.components[]`（成功）列出每条上游的 `name / uri / httpCode / status`；失败时 `details.errorCode = "GATEWAY_NOT_READY"`。

  **`/gateway/ready` 错误码**（与 §5.1 `gateway-auth` 错误码表同属 `GATEWAY_*` 基础设施命名空间，统一注册在 [`./backend.md §6.3`](./backend.md)）：

  | HTTP 状态 | 场景 | `details.errorCode` | `message` |
  |---|---|---|---|
  | `503` | 任一 probe 非 200 / 超时 / upstream 不可达 | `GATEWAY_NOT_READY` | `"One or more upstream services are not ready"` |

  `/__ready_probe/*` 是 gateway **内部 location**（`internal;` 指令），外部不可访问。新增业务服务时**两处同改**（见 §7）：（a）在 `config.yaml.template` 的 nginx server 段追加 `/__ready_probe/<service>` internal location 并配 `proxy_connect_timeout` / `proxy_read_timeout` 与 plugin schema 里的 `timeout_ms` 对齐；（b）在 `apisix.yaml` 的 `gateway-ready` plugin 配置 `probes[]` 里追加一条。不做"自动服务发现"；不存在"不聚合"选项。

  **具体挂点（硬规则，避免歧义）**：internal location 必须声明在 **`config.yaml.template` 的 `nginx_config.http_server_configuration_snippet`**（或等价的 APISIX `apisix.nginx_config.http_server_configuration_snippet`）字段下——即 APISIX 的 `server { ... }` 块内部、与 APISIX 自身的 `location /` 同级。不要写进 `http_configuration_snippet`（那是 `http { ... }` 顶层，`internal;` 指令与 `proxy_pass` 无法就近在 server 上下文生效），也不要单开独立 `server { ... }` 块（`ngx.location.capture_multi` 只在同一 server 内部定位子请求，跨 server 的 sub-request 会打回 APISIX 的主路由表而不是 internal location，导致绕路 + 可能命中兜底路由）。

  **形态示例**（按 `<service>` 填充；`proxy_*_timeout` 与对应 `probes[i].timeout_ms` 数值相等）：

  ```yaml
  # config.yaml.template 片段
  apisix:
    nginx_config:
      http_server_configuration_snippet: |
        location = /__ready_probe/auth {
          internal;
          proxy_connect_timeout 1s;
          proxy_send_timeout    1s;
          proxy_read_timeout    1s;
          proxy_pass http://auth-service:8081/health;
        }
        location = /__ready_probe/assistant {
          internal;
          proxy_connect_timeout 1s;
          proxy_send_timeout    1s;
          proxy_read_timeout    1s;
          proxy_pass http://assistant-service:8082/health;
        }
  ```

  **错误码映射**：某条 internal location 不存在 / 拼写错时，`ngx.location.capture` 返回 `ngx.HTTP_NOT_FOUND`（404），`gateway-ready` 插件一律将 `< 200 || >= 300` 视为 probe 失败，计入聚合 503；该失败在响应体 `details.components[i].httpCode` 保留原值，便于运维定位"是真挂了还是 gateway 自己漏配 location"。

  **超时契约与实际强制**：`timeout_ms` / `total_timeout_ms` 在 plugin schema 里只是**声明式契约**，Lua 层不直接强制（`ngx.location.capture_multi` 未开放 per-subrequest 超时参数）；真正的超时必须在对应内部 location 的 `proxy_connect_timeout` / `proxy_read_timeout` 上落地。两处数值保持一致是接入硬要求。

  **硬规则**（不落地即视为配置错误）：

  - `total_timeout_ms` **仅为声明值**，Lua 侧不实际强制；它是给运维 / PR reviewer 的**预算契约**，用于和每条 probe 的 `timeout_ms` 比对。
  - **真正的单 probe 熔断**必须落在 nginx 层：每条 probe 对应的 internal location 的 `proxy_connect_timeout` / `proxy_read_timeout`（或 `proxy_send_timeout`）必须显式设置，且**数值 = 该 probe 的 `timeout_ms`**——不允许 internal location 用 nginx 默认值（通常为 60s）。
  - **预算守恒约束**：`Σ 各 probe timeout_ms ≤ total_timeout_ms`。违反即预算失真——某条 probe 超时后下一条仍会继续探测，`/gateway/ready` 的整体响应延迟会超过 `total_timeout_ms`。PR review 阶段由 reviewer 以该不等式作为**可机械验证**的判据；未来由 `scripts/check-gateway-config.py` 自动断言。
  - 不允许引入"整体硬截断"（例如 gateway-ready 插件内部 spawn 计时器到点 `ngx.exit`）作为绕过手段——该路径会与 `ngx.location.capture_multi` 的响应聚合语义冲突，产生半收集状态。

  **不做的事**：不并联探数据库、不并联探第三方、不做分级健康（degraded/warning），只做"每个上游 `/health` 是否 200"的布尔 AND。数据库/第三方的降级由各业务服务自己的 `/health` 决定。

  **聚合语义的局限性（刻意选择）**：由于 [`./backend.md §7.1`](./backend.md) 硬规则要求 `/health` **不级联**探 DB/缓存/LLM/第三方，`/gateway/ready` 也就**不**反映"数据库连通性 / schema 已初始化 / LLM provider 可达"等更深层的就绪状态；它只表达**"各上游进程存活且 `/health` 返 200"**这一层。冷启动阶段的 "`pixels_auth` / `pixels_analysis` schema 是否已创建"、"必填环境变量是否注入" 等一次性校验由仓库的 `scripts/smoke.sh` 直接连 MySQL / 直接读配置完成，**不**塞进本路由。任何"把 DB 可达性/配置检查塞进 `/gateway/ready`"的提案都应先检查是否属于"冷启动一次性验证"而非"持续就绪度"，前者永远应走 smoke / 运维脚本。

### 4.2 Docker 容器健康检查必须用 `/gateway/live`

```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "http://localhost:9080/gateway/live"]
```

**反例（当前代码的问题）**：把 `/gateway/health` 通过 `proxy-rewrite` 转给 auth-service。这会让"auth-service 抖动"误判为"gateway 不健康"，触发不必要的 gateway 重启，并把故障放大到"两个服务同时看起来都挂了"。

### 4.3 upstream 健康检查与此分开

APISIX 对 upstream 节点的健康检查（`checks.active`）是网关内部的事，与本文 §4.1 的两条路由无关；需要时可以在 upstream 声明里单独配。

---

## 5. `gateway-auth` 插件契约

### 5.1 插件职责

- 读取身份凭据：**仅 Cookie**（`access_token`）。**不支持 `Authorization: Bearer`**。
- 补齐 / 透传 `X-Request-Id`。
- 补齐 `X-Forwarded-For` / `X-Forwarded-Proto` / `X-Forwarded-Host`。
- 在受保护路由上执行 CSRF double-submit 校验（cookie `XSRF-TOKEN` vs header `X-XSRF-TOKEN`）。
- 调 auth-service `POST /api/internal/auth/introspect`，带 `X-Internal-Auth: ${INTERNAL_INTROSPECTION_SECRET}`。
- 在校验成功后清空并重新注入身份头：
  - `X-Auth-User-Id`
  - `X-Auth-User-Email`
  - `X-Auth-Session-Id`（可选）
- 错误响应统一 schema：`{ code, message, requestId, details? }`，与业务服务 `backend.md §6.3` 完全对齐。

**Secret 注入硬规则（Standalone YAML 模式专属）**：

- 插件实例配置中出现的 **`INTERNAL_INTROSPECTION_SECRET`** / **`INTERNAL_GATEWAY_ADMIN_SECRET`** / 其他任何 secret，在 `apisix.yaml` 里一律以 `${SECRET_NAME}` 占位符出现，由 `entrypoint.sh` 启动阶段通过 `envsubst`（或等价 Lua 侧 `os.getenv`）渲染落位。**禁止**以明文或默认占位值提交进 git。
- `gateway-auth` 插件本身在 Lua 层读 secret 的路径也必须统一为 `os.getenv("INTERNAL_INTROSPECTION_SECRET")` 或 APISIX 的 `core.env.fetch_by_uri`，**禁止**从 plugin config 里反复读 secret 字段（schema 里只保留 `introspection_url` 这种非敏感字段）。
- `entrypoint.sh` 在 env 缺失时**必须 fail fast**（见 [`./backend.md §13`](./backend.md) 的启动期硬校验同源原则），不走"渲染出空串"的静默失败路径。涉及 env 变量清单集中在 [`../../.env.example`](../../.env.example)。`code` 等于 HTTP 状态码，`details.errorCode` 使用下表的固定串：

  | HTTP 状态 | 场景 | `details.errorCode` | `message` |
  |---|---|---|---|
  | `401` | 未登录 / token 无效 / session 已撤销 | `GATEWAY_AUTH_REQUIRED` | `"Authentication required"` |
  | `403` | CSRF 校验失败 | `GATEWAY_CSRF_INVALID` | `"CSRF validation failed"` |
  | `503` | introspect 调用失败或返回不完整 | `GATEWAY_INTROSPECT_UNAVAILABLE` | `"Authentication service unavailable"` |

  这三个 errorCode 与 `GATEWAY_IDENTITY_MISSING`（backend.md §3.3）同族，统一使用基础设施前缀 **`GATEWAY_*`**——它表达的是"接入面基础设施故障/判定"，不属于任何业务领域。与之对应，`INTERNAL_AUTH_FAILED`（backend.md §8.6）使用 `INTERNAL_*` 前缀，表达的是"跨服务内部通信基础设施故障"。业务领域前缀（`AUTH_*` / `ANALYSIS_*` 等）与基础设施前缀在命名空间上严格互不重叠（见 backend.md §6.3）。

### 5.2 路由配置参数

| 参数 | 默认 | 含义 |
|---|---|---|
| `introspection_url` | 必填 | auth-service 的 introspect 地址 |
| `require_auth` | `true` | 是否要求身份存在；`false` 用于登录/注册等公开路由 |
| `csrf_protect` | `true` | 是否做 CSRF double-submit（安全方法会自动豁免） |
| `positive_cache_ttl` | `30` | 校验通过结果的缓存秒数；与 §5.3 主动失效接口绑定落地，不再保留"落地前降到 10s"的过渡值 |
| `negative_cache_ttl` | `5` | 校验失败结果的缓存秒数 |
| `introspect_timeout_ms` | `800`（建议范围 `200~2000`） | 单次 introspect 子请求的超时上界。必须在底层 `httpc:set_timeout` 或 `ngx.location.capture` 等价机制上落地，**禁止**硬编码在 Lua 常量里 |
| `introspect_total_budget_ms` | `1500` | "cache miss + 单次 introspect + 排队"的端到端预算。超时即回 `503 + GATEWAY_INTROSPECT_UNAVAILABLE`，**不**把未完成请求阻塞等 positive cache 自然到期 |

**超时字段的硬约束**：

- `apisix.yaml` 每条受保护路由**必须显式声明** `introspect_timeout_ms` 与 `introspect_total_budget_ms`，不得依赖插件默认值——与 `positive_cache_ttl` / `negative_cache_ttl` 同一批评估。
- 失败路径（introspect 超时 / 连接失败）仍写 **negative cache**（`negative_cache_ttl` 秒），避免 auth-service 故障时同一 token 被打到雪崩。
- 结构化日志必须包含 `introspect_elapsed_ms` 字段，便于阈值调优。

**四类路由的标准 plugin 配置组合**（避免新同学反复猜）：

| 路由类别 | 示例 | `require_auth` | `csrf_protect` | 理由 |
|---|---|:-:|:-:|---|
| 受保护业务路由 | `/api/v1/conversations*` 等业务路由；auth-service 的用户面接口 `/api/v1/auth/me`、`/api/v1/auth/logout`、`/api/v1/auth/logout-all`、`/api/v1/auth/sessions*` | `true` | `true` | 默认形态。auth-service 的用户面接口与普通业务服务无本质差异，身份来源是 gateway 注入的 `X-Auth-*` 头（见 [`./backend.md §3.4`](./backend.md)） |
| 公开无凭据 POST | `/api/v1/auth/login`、`/api/v1/auth/register`、`/api/v1/auth/captcha` | `false` | `false` | 未登录用户没有 `XSRF-TOKEN` cookie；这类路由不携带任何已认证 cookie，不构成 CSRF 攻击面。这里三条是 auth-service 实际存在的公开路由，**与 [`./backend.md §3.4`](./backend.md) 的公开路由表严格一致** |
| 公开但携带 cookie 的 POST | `/api/v1/auth/refresh` | `false` | **`true`** | 该路由**依赖** `refresh_token` cookie 且可在 `access_token` 已过期时被调用（此时 gateway 的 `require_auth` 判定会失败，故必须 `false`）；若不开 CSRF，攻击者可凭 victim 的 refresh_token cookie 悄悄续 session。**强制开 CSRF double-submit**，前端调用前必须先有 `XSRF-TOKEN`（登录后 auth-service 会 set-cookie） |
| 安全方法 | `GET /*` | 随业务 | — | `gateway-auth` 对安全方法（GET/HEAD/OPTIONS）自动豁免 CSRF |

**`/api/v1/auth/logout` 归类说明（避免与 refresh 混淆）**：

- `logout` 的**所有合法调用方都是已登录用户**，走 `require_auth=true` + `csrf_protect=true` 是正确形态。
- 若错误地配成 `require_auth=false`，未登录用户访问 `logout` 时 gateway 不会注入 `X-Auth-User-Id`，auth-service 再由 `@RequestHeader("X-Auth-User-Id", required=true)` 抛出 `MissingRequestHeaderException` → `500 + GATEWAY_IDENTITY_MISSING`——这会把业务错误包装成"接入面事故"，触发 critical 告警，完全不合理。
- `refresh` 与 `logout` 的核心区别：`refresh` 必须能在 access_token 过期时调用（此时 gateway 无法 authN），因而**必须**公开；`logout` 的预期调用场景是"用户仍登录时主动退出"，因而**必须**受保护。两者绝不能归同一类。

**CSRF 校验语义硬规则**：`csrf_protect: true` 的路由，**除安全方法**（GET/HEAD/OPTIONS）**外一律执行** double-submit 校验，**不**以"请求是否携带 auth cookie"作为跳过判据。缺 `XSRF-TOKEN` cookie 或 header-cookie 不匹配，一律判 `GATEWAY_CSRF_INVALID`。

- **反例（必须删除）**：当前 `gateway-auth.lua:should_skip_csrf` 的逻辑大致是 `if not access_cookie and not refresh_cookie then return true`——即"未携带任何 auth cookie 时跳过 CSRF"。这对 `/api/v1/auth/refresh` 与 `/api/v1/auth/logout` 这类"公开但携带 cookie 的 POST" 形成攻击面：攻击者可以用未登录状态下触发的无 cookie POST 绕过校验。
- **正确形态**：Lua 侧只看 `csrf_protect` 配置项 + 请求方法；有无 cookie 与是否校验 CSRF **完全解耦**。

**注意**：当前代码的默认值是 `positive_cache_ttl=2` / `negative_cache_ttl=1`，会严重放大 auth-service 压力。切换到 Standalone YAML 时，`apisix.yaml` 的每条 route **必须显式写死** `positive_cache_ttl: 30` / `negative_cache_ttl: 5`，并与 §5.3 的主动失效接口一同落地，不依赖插件默认值。

**login 的未来硬化预留**：当前 `/api/v1/auth/login` 与 `/api/v1/auth/register` 只做 `require_auth=false` + `csrf_protect=false`，**不**做 Origin / Referer 校验——本地开发与测试工具（curl / Postman）都不带这两个头，硬校验会让初始化验证路径无法跑。未来若出现定向暴力登录或凭据填充（credential stuffing）事件需要硬化时，**统一通过环境变量 `GATEWAY_ORIGIN_ALLOWLIST`（逗号分隔的 allowlist）在 gateway 层校验**，由 `gateway-auth` 插件在受影响路由上消费该变量；**不在 auth-service 内实现** Origin / Referer 校验逻辑（违反 §3 的"AuthN 在 gateway"硬规则）。本节作为预留入口：实现时在本节更新示例配置、在 `.env.example` 声明 `GATEWAY_ORIGIN_ALLOWLIST` 默认值、在 `scripts/check-gateway-config.py` 加相应断言。当前阶段**只预留不实现**。

#### 5.2.1 `XSRF-TOKEN` / `access_token` / `refresh_token` cookie 属性（硬约束）

Double-submit CSRF 校验能成立的前提是 **`XSRF-TOKEN` cookie 对 JS 可读**（否则前端无法把它放进 `X-XSRF-TOKEN` 请求头），而 **`access_token` / `refresh_token` 对 JS 不可读**（否则受 XSS 威胁时 token 直接泄露）。cookie 属性必须严格按下表设置，由 `auth-service` 在登录 / 刷新 / 注销成功时下发，gateway 不转译不覆写：

| Cookie | `HttpOnly` | `Secure` | `SameSite` | `Path` | TTL | 备注 |
|---|:-:|:-:|:-:|---|---|---|
| `access_token` | ✅ true | ✅ true（生产）/ 仅本地 dev 可 false | `Lax` | `/` | 短期（与 JWT `exp` 对齐） | JS 永远读不到；浏览器自动随同源请求携带 |
| `refresh_token` | ✅ true | ✅ true（生产）/ 仅本地 dev 可 false | `Strict` | `/api/v1/auth/refresh` | 长期（≥ access_token） | `SameSite=Strict` + `Path` 收窄：只会随 `/api/v1/auth/refresh` 请求发送，不会出现在其他路由 |
| `XSRF-TOKEN` | ❌ **false**（必须 JS 可读） | ✅ true（生产）/ 仅本地 dev 可 false | `Lax` | `/` | 登录起至 logout | 每次登录重新生成；前端 axios 拦截器读取后放进 `X-XSRF-TOKEN` 请求头 |

**硬规则**：

- 生产环境（`Secure=true`）与本地开发（`Secure=false`，因走 HTTP）由 `auth-service` 读环境变量 `COOKIE_SECURE` 切换，**不**自动探测请求协议；自动探测会在反向代理/TLS 终结点配置漂移时产生隐藏缺陷。
- `Domain` 属性**一律不显式设置**（默认 "发行方主机"），避免把 cookie 泄露到同一 apex 下其他子域名。未来启用多子域共享时再加 `Domain=.example.com` 并在本节更新。
- 三个 cookie 的属性**只由 auth-service 设置**；gateway 的 `gateway-auth` 插件**不得**改写 `Set-Cookie`，也不得凭自身逻辑 `ngx.header["Set-Cookie"]=` 改写这三个 cookie。网关若需要清除 cookie（如 invalidate_session 副作用），也通过回调 auth-service 或让 auth-service 在业务 logout 响应里自行 `Set-Cookie: xxx=; Max-Age=0`。
- **反例**：曾出现过"`XSRF-TOKEN` 设成 `HttpOnly`"的改动 —— 会直接让前端 axios 拦截器读不到 cookie，表现为所有受保护 POST 被判 `GATEWAY_CSRF_INVALID`。任何未来 PR 若把 `XSRF-TOKEN` 改成 `HttpOnly`，必须拒绝合并。

##### 5.2.1.1 `refresh_token` cookie 的清理路径（logout 必须双写）

`refresh_token` 的 `Path=/api/v1/auth/refresh` 收窄属性会让浏览器仅在这一条路由上回传；logout 成功后若仅撤销服务端 session 记录而**不**主动清这颗 cookie，浏览器侧仍会保留它直到自然过期，后续若用户切换账号、同机多账号或同一浏览器再次访问 `/api/v1/auth/refresh`，该 cookie 会被自动回传并触发"已撤销 session 的 refresh 尝试"的噪声日志。**硬规则**：`auth-service` 处理 `/api/v1/auth/logout` / `/api/v1/auth/logout-all` 的成功响应**必须同时**：

1. **服务端真源**：撤销对应 `auth_session` 记录（这是权威真源，缺它即使 cookie 被回传也会被 `introspect` 判为 `active=false`）；
2. **浏览器侧清除**：显式 `Set-Cookie: refresh_token=; Path=/api/v1/auth/refresh; Max-Age=0; HttpOnly; Secure=<same>; SameSite=Strict`（`Secure` / `SameSite` 属性必须**与原 Set-Cookie 完全一致**，否则浏览器会视为不同的 cookie，清不掉）。

两者缺一不可：服务端真源解决"已撤销 session 再回来会被识破"，浏览器侧清除解决"cookie 不再无意义地被回传"。同规则适用 `access_token` / `XSRF-TOKEN`。

### 5.2.2 `/api/v1/auth/refresh` 的三重特殊性

`/api/v1/auth/refresh` 在 gateway 配置空间里是一条**极其反直觉**的路由，历史上每次"看起来只是改一个参数"的 PR 都会踩到它。集中说明避免重复犯错：

1. **公开（`require_auth: false`）**。它**必须**能在 `access_token` 已过期时被调用——这正是 refresh 存在的意义。若配 `require_auth: true`，gateway 在 access_token 过期时会直接返 `401 GATEWAY_AUTH_REQUIRED`，客户端永远走不到 refresh 逻辑。
2. **强制 CSRF（`csrf_protect: true`）**。它**携带 `refresh_token` cookie**，属于"无需 AuthN 但有已认证 cookie 被浏览器自动回传"的少数路由。若不开 CSRF double-submit，攻击者可用第三方站点触发无 header 的跨站 POST，凭 victim 的 `refresh_token` cookie 悄悄续 session，形成会话劫持。
3. **不挂 `JwtAuthenticationFilter`**（auth-service 侧硬规则，见 [`./backend.md §3.4`](./backend.md)）。controller 层从 `refresh_token` cookie 取字符串、交给 `SysLoginService` 做业务轮换与 session 活性判断；**不**把 JWT 解码作为"识别当前请求者身份"的手段。

**三件事同时存在**的根因是 refresh 同时兼具"未认证入口"（过期可用）、"已认证副作用"（会种新 cookie）、"业务领域 token 处理"（不是身份识别）。任何一条缺席都会形成攻击面或功能缺陷；任何一条被"简化"（例如为方便测试把 CSRF 关掉）都会在生产形成严重漏洞。PR review 遇到 refresh 相关改动必须对照本节三条逐项校对。

### 5.3 Session 主动失效接口（契约）

当用户 logout 或会话被撤销时，`auth-service` 主动调 gateway 的"吹缓存"接口让 gateway 提前清除该 token 的 positive cache。该接口与 `positive_cache_ttl = 30s` 的假设**绑定落地**：有它，30s TTL 才安全；没它，TTL 必须压到近乎 0。因此**不设"过渡期"**——把接口与 standalone YAML 迁移放到同一个 PR 落地。

**联动不变量（硬规则，由 `scripts/check-gateway-config.py` 机械断言）**：

- 若 `apisix.yaml` 中任一 `gateway-auth` route 声明的 `positive_cache_ttl > 5`，则**必须**同一 `apisix.yaml` 中存在 `/gateway/internal/invalidate_session` 的 internal route 声明（含 `X-Internal-Auth` 校验）；反之若没有主动失效路径，所有 `gateway-auth` route 的 `positive_cache_ttl` 必须 ≤ 5——否则构成"用户 logout 后缓存仍有效若干十秒"的安全窗口。
- 该断言是防止未来某次 PR"只降 TTL 忘记补主动失效"或"只拆主动失效忘记压 TTL"两类单向漂移的唯一机械保障；PR review 不要人工判断，一律 CI 跑 `check-gateway-config.py`。

#### 5.3.0 设计特许：这是**唯一允许的反向依赖**

默认形态下业务服务（含 auth-service）**不得**主动调 gateway——gateway 是接入面，不应被业务代码感知。本节的 `POST /gateway/internal/invalidate_session` 是**目前唯一被显式特许**的反向依赖，原因是：

- 主动吹缓存是**缓存一致性问题的根属性**，只能由"拥有会话真源的一方"主动通知"持有派生缓存的一方"，方向天然反转；
- 没有这条反向调用，`positive_cache_ttl` 必须压到极低（≈ 2s），auth-service 会被 introspect 压力打爆；
- 该接口不承载业务语义，只承载基础设施层的失效事件，因此不构成"业务耦合向 gateway 泄露"。

**约束**：任何新增的 `auth-service → gateway` 或 `business-service → gateway` 反向调用提案，**必须先在本节追加一个特许条目**并说明"为什么默认方向不可行"，否则 PR 拒绝合并。其他反向依赖的默认答案是 **No**。

#### 5.3.1 对外契约

- **URL**：`POST /gateway/internal/invalidate_session`
- **调用方**：仅 `auth-service`（短期），未来可扩展到其他可信服务。
- **路由保护**：
  - 在 `apisix.yaml` 里声明为 **internal 路由**：匹配 `/gateway/internal/*`，**禁止对外 route**（例：为 `/gateway/internal/*` 单独开一条 route，upstream 指向网关自身实现的 lua handler，或挂一个 `serverless-pre-function` 插件承载逻辑）。
  - 校验 header `X-Internal-Auth: ${INTERNAL_GATEWAY_ADMIN_SECRET}`（与 introspect secret 是**不同** secret，避免权限扩散）。
  - **可选加固**：在 route 上加 `ip-restriction`，白名单通过 `INTERNAL_NETWORK_CIDR` 环境变量注入（compose 部署可传 `172.16.0.0/12, 10.0.0.0/8, 127.0.0.0/8` 之类的超集）。**不依赖此条作为主防护**——compose 网段可能每次重建变化，secret 是硬边界、ip-restriction 是软边界。
- **请求体**：
  ```json
  {
    "sessionId":       "optional, invalidate one session by sessionId",
    "userId":          "optional, invalidate ALL sessions of this user",
    "accessTokenHash": "optional, invalidate one token by its sha256 hex"
  }
  ```
  三者至少传一个；多字段同时传时按"或"语义累加清除。
- **响应**：`200 { "code": 200, "message": "success", "data": { "invalidated": <count> }, "requestId": "..." }`（与 `backend.md §6.1` 成功 schema 对齐）。
- **失败响应**：凭据错返 `500 + details.errorCode="INTERNAL_AUTH_FAILED"`，与 `backend.md §8.6` 完全一致。**不使用 401/403/503。**
- **幂等**：同一请求重复调用结果一致（清空已空的 cache 不报错，`invalidated` 返回实际命中次数）。
- **失败降级**：`auth-service` 调用超时/失败时**不影响** logout 主流程；gateway cache 会在 `positive_cache_ttl` 到期时自然失效。auth-service 侧可记录 WARN 日志，但**不重试**（重试会把"用户已 logout"的窗口拉长，不是缩短）。

#### 5.3.2 Gateway 内部实现：cache key 与反向索引

为了让三个清除维度（`sessionId` / `userId` / `accessTokenHash`）都 O(1) 命中，gateway 侧维护三张 `lua_shared_dict`：

| Shared Dict | Key | Value | 用途 |
|---|---|---|---|
| `gateway_auth_cache`（主缓存） | `introspect:<sha256(token)>` | 序列化的 introspect 响应 | `gateway-auth` 查询身份的热路径 |
| `gateway_auth_session_index` | `sess:<sessionId>` | `<sha256(token)>`（单值） | sessionId → tokenHash 反查 |
| `gateway_auth_user_index` | `user:<userId>:<sha256(token)>` | `1`（标记值；存在即表示该用户持有此 tokenHash） | userId → tokenHash 反查；**每个 tokenHash 独立成 key**，不对"一个数组 value"做 read-modify-write |

**写入时机**：`gateway-auth` 每次 introspect 成功后，除了写主缓存，**同步更新**两个反向索引（`sessionId` 与 `userId` 取自 introspect 响应）。索引的 TTL 与主缓存同步（`positive_cache_ttl`），过期后反向索引条目一起被动失效，不用额外 GC。

- 具体写入调用使用 `gateway_auth_user_index:set(key, "1", ttl)`（或 `add`，让并发重复写入幂等）；**禁止**使用 "`get → decode → push → encode → set`" 这种 read-modify-write 序列。

**清除逻辑**：

- 按 `accessTokenHash` 清：直接 `gateway_auth_cache:delete("introspect:" .. hash)`；同时调用 `gateway_auth_user_index:delete("user:" .. userId .. ":" .. hash)`（userId 可从主缓存删除前取到），以及 `gateway_auth_session_index:delete("sess:" .. sessionId)`（sessionId 同上）。
- 按 `sessionId` 清：`gateway_auth_session_index:get("sess:" .. sessionId)` 拿到 tokenHash，然后走按 `accessTokenHash` 清的逻辑。
- 按 `userId` 清：`gateway_auth_user_index:get_keys(0)` 遍历 dict 内所有 key，以前缀 `user:<userId>:` 过滤出该用户持有的所有 tokenHash，对每个执行按 `accessTokenHash` 清的逻辑。invalidate 接口是低频操作，线性扫描可接受；若未来用户量/token 量使扫描成为瓶颈，再评估拆 per-user dict 或引入 `resty.lock` 聚合 value，不在当前阶段做。

**硬规则**：

- 反向索引**只是为 invalidate 接口服务的加速结构**，不作为其他业务路径的数据源；不允许在身份注入链路上读这两个 dict。
- **禁止对任何 `lua_shared_dict` 的 value 做 read-modify-write**（如"取出 JSON 数组、push 新元素、再写回"）——`lua_shared_dict` 无事务语义，这种访问模式在并发下必然丢写。所有"一对多"反向索引都用 key-per-member 展开（如上 `user:<userId>:<tokenHash>`），依赖 `set` / `add` / `delete` 的原子性。该硬规则对未来新增的任何 gateway 侧内存结构都适用。

**`config.yaml` 必须同步声明三张 shared_dict**（切到 Standalone YAML 时一并落地，不保留"先主缓存、后反向索引"的中间态）：

```yaml
nginx_config:
  http_configuration_snippet: |
    lua_shared_dict gateway_auth_cache          10m;
    lua_shared_dict gateway_auth_session_index  5m;
    lua_shared_dict gateway_auth_user_index     5m;
```

容量基线：主缓存 10m（约 5 万 introspect 条目）、session 反向索引 5m（单值条目小，容量够用 ~10 万）、user 反向索引 5m（值是数组，按用户平均 2 个活跃 token 估算容量相当）。**真实容量按生产 token 发放量调整**，但三张的声明本身必须随 Standalone YAML 同一次改动进入，不允许漏声明。

#### 5.3.3 此设计绑定 §1.2 的单实例部署假设

`lua_shared_dict` 是 **per-nginx-process**（一个 APISIX 实例内所有 worker 共享），**不跨实例**。本节的三张 dict + `POST /gateway/internal/invalidate_session` 只能让"调用到的那台实例"失效；一旦 gateway 横向扩容到 ≥ 2 实例，invalidate 就只能摧毁其中一部分缓存，其它实例的 `positive_cache_ttl` 仍然按原值自然衰减——这不是"窗口变长 30s"这种可以接受的退化，而是直接破坏 §5.3.0 特许反向调用的正当性（特许的前提是"反向调用能让缓存即刻失效"）。

横向扩容到多实例前必须回本节重新评估，候选方向：

- **外部 KV**：把 introspect 缓存从 `lua_shared_dict` 迁到 Redis（或等价组件），所有实例共享同一份状态；`invalidate_session` 直接改写 Redis。
- **广播模型**：gateway 自身订阅 auth-service 的 invalidate 事件（消息队列 / pub-sub），各实例各自处理自己的本地 dict。
- **短 TTL 退化**：把 `positive_cache_ttl` 压回 ≈ 2s 接受 auth-service 压力——只适合过渡期紧急方案。

当前阶段锁定"单实例 + 本地 dict"路径，`gateway.md §1.2` 的"触发重新评估的信号"第一条（多实例集群同步）即本节的重新评估入口。本节设计**不得**在未回到 §1.2 做选型决策前被扩展为跨实例形态。

### 5.4 禁止事项

- ❌ 不允许新增"从 `Authorization: Bearer` 读 token"的分支（Web 单端场景下无用户）。
- ❌ 不允许在插件里直接访问 `document` / `window`（Lua 层无此问题，但等价是"不要直接读 nginx 全局状态"）。
- ❌ 不允许让插件去查业务库。
- ❌ 不允许把 `INTERNAL_INTROSPECTION_SECRET` 以任何形式写进日志或 debug 响应。

---

## 6. 路由规范

### 6.1 URI 前缀按领域

- `/api/v1/auth/*` → auth-service
- `/api/v1/analysis*` / `/api/v1/conversations*` / `/api/v1/semantic*` / `/api/v1/analysis/backends*` → assistant-service（未来可按领域拆服务）。**注意**：`/api/v1/analysis/backends*` 是 `/api/v1/analysis*` 的更深子资源前缀，`priority` 必须显式声明高于父前缀，见 §6.2
- `/api/v1/auth/openapi.json` → auth-service 的 `/openapi.json`（见 §6.7）
- `/api/v1/analysis/openapi.json` → assistant-service 的 `/openapi.json`（见 §6.7）
- `/api/internal/*` → 仅网关内部或可信服务调用，**绝不对外 route**（见 `backend.md §8.6`）
- `/gateway/live` / `/gateway/ready` → 网关内部健康检查
- `/gateway/internal/*` → 网关内部管理接口（如 `/gateway/internal/invalidate_session`，见 §5.3），**绝不对外 route**
- `/*` → frontend upstream（长期形态）

**新增领域时**：必须按领域前缀申请，不按实现细节拆（反例：不允许出现 `/api/v1/mysql-thing/*` 这种以实现暴露的前缀）。

**历史纠偏**：原 `/api/v1/backends*` 前缀（"后端实现类型"查询）**违反**按领域命名原则——"backend 实现"本身是一种实现细节而非领域。已归入 analysis 域作为其子资源 `/api/v1/analysis/backends*`。新代码与 apisix.yaml 配置必须使用新前缀。

### 6.2 路由优先级

- 高具体度优先：`priority` 数值越大越先匹配。
- 兜底 `/*` → `frontend` 必须保持 `priority: 1`，**永远不要提高**。
- `/api/v1/auth/login` 等具体路径 `priority ≥ 900`。
- `/api/v1/xxx/*` 前缀匹配 `priority ≥ 800`。
- **深前缀压浅前缀（硬规则）**：若两条 route 的 URI 存在前缀包含关系（如 `/api/v1/analysis/backends*` ⊂ `/api/v1/analysis*`），深前缀的 `priority` 必须显式声明**比浅前缀高 ≥ 10**。相等时匹配顺序由 APISIX 实现细节决定，**不构成稳定契约**，PR 必须拒绝合并。

### 6.3 超时

- 默认业务 upstream 超时：connect ≤ 2s、send ≤ 5s、read ≤ 30s。
- **SSE / 长轮询路由必须单独声明**：read 超时至少 10 分钟，或设置为 0 (无限)；同时在 upstream 层禁用响应缓冲。
- LLM 相关路由读超时可以更长，但必须**显式写出**，禁止依赖默认值。

### 6.4 CORS

- **唯一入口**：CORS 只在网关的 `cors` 插件里配置，使用 `CORS_ALLOWED_ORIGINS` 环境变量注入。
- 所有后端服务的 CORS（例如 `assistant-service` 的 `allow_origins=["*"]`）**必须关闭**。

### 6.5 限流

- 所有已认证业务路由应有基础 `limit-count` 或 `limit-req`，按用户 id 维度（以 `X-Auth-User-Id` 为 key）。
- 未认证路由（login / register / captcha）按客户端 IP 限流，防暴力。
- SSE 路由独立限制"并发订阅数"，不要和普通 REST 路由混在一起。

### 6.6 安全响应头（由 gateway 一层下发）

> **硬规则（显眼位置）**：本节描述的所有安全响应头由 gateway **一层**下发，对**所有 route 生效**——包括 `/api/v1/**` 业务路由、`/gateway/live` / `/gateway/ready` / `/gateway/internal/**` 管理路由、`/*` 兜底 frontend 静态分发路由。业务服务与前端容器**不得**重复下发同名响应头。这一硬规则与 §2.0 的单实例总纲同源——多处下发会导致漂移源增倍，且在扫描器 / 合规工具视角下产生误报。

所有 HTTP 响应由 gateway 统一补齐下列响应头。**业务服务与前端容器不再下发同名响应头**，避免重复与漂移。实现方式：APISIX 的 `response-rewrite` 插件在全局或全路由开启。

| 响应头 | 策略（初始值） | 语义 |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | 强制 HTTPS 一年；仅在生产开启（本地开发可通过环境变量关闭） |
| `X-Frame-Options` | `DENY` | 禁止被任何站点 iframe 嵌入，防点击劫持 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | 跨域仅发 origin，不发 path/query |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=()` | 全部关闭；产品若用到某能力再显式打开 |
| `X-Content-Type-Options` | `nosniff` | 禁用 MIME 嗅探 |
| `Content-Security-Policy` | `default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` | 基线策略：仅允许同源；`style-src 'unsafe-inline'` 是 AntD 需要（后续可通过 nonce 收紧） |

**落地方式（全局生效）**：安全头通过 APISIX 的 `global_rules`（或等价的全局 `response-rewrite`）下发，**对所有路由生效**，包括：

- 所有 `/api/v1/**` 业务路由；
- `/gateway/live`、`/gateway/ready`、`/gateway/internal/**` 网关自身管理路由；
- `/*` 兜底的 frontend 静态分发路由。

**不做"只对业务路由加头、管理路由不加头"的差异化**——差异化会在扫描器 / 合规工具视角下产生"同一 host 某些 path 缺头"的噪声告警，且没有真实安全收益。

**运维约束**：

- CSP 每次收紧前必须先在生产开 `Content-Security-Policy-Report-Only` 至少一周观察告警。
- HSTS 一旦上线不可回退（浏览器缓存 `max-age` 内必须保持 HTTPS 可用）；生产启用前确认 TLS 证书自动续期已就绪。
- `script-src` 未来引入外部 CDN / 第三方脚本时，必须走 PR 白名单，不得随手 `'unsafe-inline'`。
- **TODO — `style-src 'unsafe-inline'` 去除路径**：当前值为 AntD 5 运行时样式注入所需。升级到支持 CSS nonce 的 AntD 版本（或改用 static CSS 提取方案）后，应改为 `style-src 'self' 'nonce-<per-request>'`，并在 gateway 层为每个响应注入 nonce 到 HTML 模板；在该升级完成之前不得在 `script-src` 上复用同样的"临时放宽"理由。

**开发/本地环境 CSP 放宽条款**：生产基线的 `script-src 'self'` 会直接打断 Vite dev server 的 HMR（需要 `ws:` / `wss:` + 运行时求值），本地 `docker compose up` 若命中生产基线将出现"登录后前端白屏、控制台一堆 CSP violation"。落地形态：

- `apisix.yaml` 为"生产 CSP"与"开发 CSP"各准备一条**互斥的** route 级 `response-rewrite`（或 `global_rules`）声明，挂载哪一条由环境变量 `GATEWAY_CSP_PROFILE` 决定（允许值：`production` / `development`）；**不在运行时拼接字符串**。
- **开发 CSP** 形态（仅当 `GATEWAY_CSP_PROFILE=development`）：
  - `default-src 'self'`
  - `script-src 'self' 'unsafe-eval' 'unsafe-inline'`
  - `connect-src 'self' ws: wss:`
  - `img-src 'self' data:`；`style-src 'self' 'unsafe-inline'`；其余头（HSTS / XFO / Referrer-Policy / Permissions-Policy / `X-Content-Type-Options`）与生产基线一致。
- `.env.example` 必须显式声明 `GATEWAY_CSP_PROFILE`，默认值留空（即两条都不挂 → gateway 启动失败），强制每个部署显式选择 profile。**禁止**把 `development` 设为默认值。

### 6.7 OpenAPI 文档的对外暴露

每个业务服务内部都有 `/openapi.json`（FastAPI 默认）或等价产物。暴露策略：

- **对外路径按服务命名空间重写**：
  - `assistant-service` 的 `/openapi.json` → gateway 暴露为 `/api/v1/analysis/openapi.json`
  - `auth-service` 的 `/openapi.json`（springdoc 需显式配置 `springdoc.api-docs.path=/openapi.json`，见 [`./backend.md §9`](./backend.md)）→ gateway 暴露为 `/api/v1/auth/openapi.json`
  - **所有服务内部路径硬性统一为 `/openapi.json`**（见 `backend.md §9`）；gateway 侧的 `proxy-rewrite` 只做命名空间前缀剥离，不按服务分别写死 `/v3/api-docs` 等框架默认路径。
  - **禁止** 在 gateway 上直接暴露 `/openapi.json` 这种裸路径——它会在浏览器地址栏看起来像"全站 openapi"，实际只是某一个服务的。
- **访问控制**：
  - 生产：`gateway-auth` 配 `require_auth: true`、`csrf_protect: false`（GET 请求），仅登录用户可见。
  - 开发：在 compose 里通过环境变量 `GATEWAY_OPENAPI_PUBLIC=true` 开放给匿名访问，配合 `apisix.yaml` 里两条**互斥**的 route 定义（按 env 选一条挂载）。
  - **渲染期互斥机制（硬约束，与 §6.6 CSP profile 同源）**：APISIX Standalone YAML **不支持**运行时条件路由，两条互斥 route 必须在 `entrypoint.sh` 渲染 `apisix.yaml` 的阶段依 `GATEWAY_OPENAPI_PUBLIC` 取值**二选一挂载**——实现形态与 §6.6 的 `GATEWAY_CSP_PROFILE` 完全对齐：`apisix.yaml.template` 里准备 `openapi-public.yaml.fragment` / `openapi-protected.yaml.fragment` 两个 fragment，`entrypoint.sh` 按环境变量 `envsubst` + 片段 include 出唯一一份最终 `apisix.yaml`；**禁止**运行时字符串拼接、**禁止**两条 route 同时存在（同一 URI 的 route 重复注册 APISIX 行为未定义）。
  - `.env.example` 必须显式声明 `GATEWAY_OPENAPI_PUBLIC`，默认值留空（= 未选择），`entrypoint.sh` 在空值或非法值时 fail fast，强制每个部署显式选择一条路由形态。**禁止**把 `true` 设为默认值（与 §6.6 的 CSP profile 空值拒绝启动同规则）。
- **不聚合**：不做"统一的 `/api/openapi.json` 把所有服务合并"这类事。每个服务各自拥有自己的 schema，合并由前端工具或 CI 做离线产物，不在 gateway 实时处理。
- **openapi route priority 硬规则**：`/api/v1/<service>/openapi.json` 是一个**精确路径** route（非前缀），它必须在同域下所有前缀 route 之前被匹配，否则会被 `/api/v1/<service>*` 之类的前缀路由抢先转发到服务的业务 handler 而不是 openapi endpoint。**每条 openapi route 的 `priority` 必须显式声明 > 对应域下最深业务前缀的 `priority` + 10**（例如 auth 域最深前缀 `/api/v1/auth/sessions/{id}` 若 `priority=900`，则 `/api/v1/auth/openapi.json` 必须 `priority ≥ 910`）。与 §6.2 "深前缀压浅前缀"的 +10 约束同源。`scripts/check-gateway-config.py` 应断言该规则。

---

## 7. 新增业务服务接入 Gateway 的标准动作

当需要引入一个新的业务服务（例如 `notification-service`），严格按下面 8 步：

1. **在 `docker-compose.yml` 声明服务**：`expose` 内部端口，**不 `ports`**（不对外暴露）。
2. **在 `apisix.yaml` 声明 upstream**：
   ```yaml
   upstreams:
     - id: notification
       nodes:
         "notification-service:8095": 1
       type: roundrobin
   ```
3. **规划前缀**：按领域选 `/api/v1/notifications*`，在本文档 §6.1 补记录。
4. **声明 route**：
   ```yaml
   routes:
     - id: notifications-root
       uri: /api/v1/notifications
       methods: [GET, POST, OPTIONS]
       plugins:
         gateway-auth:
           require_auth: true
           csrf_protect: true
           introspection_url: http://auth-service:8081/api/internal/auth/introspect
           positive_cache_ttl: 30
           negative_cache_ttl: 5
         limit-count:
           count: 600
           time_window: 60
           key: "http_x_auth_user_id"
           key_type: "var"
       upstream_id: notification
   ```
5. **在服务实现里消费身份头**：读 `X-Auth-User-Id` / `X-Auth-User-Email`，**禁止重新验 JWT**。
6. **补 request-id 透传**：日志里带 `X-Request-Id`，让跨服务链路能对齐。
7. **补健康检查与系统就绪聚合**：服务实现 `/health`（只探自身，不级联，见 [`./backend.md §7.1`](./backend.md)）。**同时必须**在 gateway 侧两处各追加一条 probe：（a）`config.yaml.template` 的 nginx http 段里新增一个 `/__ready_probe/<service>` 的 **internal location**（`internal;` 指令 + `proxy_pass` 到该服务的 `/health`，且 `proxy_connect_timeout` / `proxy_read_timeout` 与下一步的 `timeout_ms` 对齐）；（b）`apisix.yaml` 中 `/gateway/ready` 路由上 `gateway-ready` 插件的 `probes[]` 数组追加一条 `{ name, uri: "/__ready_probe/<service>", timeout_ms }`（见 §4.1）。**不存在"不聚合"选项**——任何新业务服务都纳入系统就绪聚合，否则 `/gateway/ready` 的"全部 200"语义在新服务上线后立刻失真。
8. **同步更新 development 文档**：在本文档 §6.1 前缀表追加新领域前缀；在 [`./backend.md §12.4`](./backend.md) 的服务拓扑表追加新服务的拥有关系、数据边界、对外 API 面。

---

## 8. 观测与审计

### 8.1 请求链路

- Gateway 保证每个入站请求有 `X-Request-Id`（缺失则生成 128-bit 随机值）。
- 该 id 透传给所有 upstream；所有后端服务在日志、trace、异步任务中都必须携带。
- 错误响应体中必须包含 `requestId`，方便用户反馈定位。

**响应头写入的唯一点（硬规则）**：

- Gateway 是出站响应 `X-Request-Id` 头的**唯一写入点**——该规则对**所有**经过 gateway 的响应成立，**无一例外**，包括以下**三种形态**：
  - **(a) 挂了 `gateway-auth` 插件的 API 路由**：正常 upstream 2xx / 4xx / 5xx 响应、gateway-auth 自身错误直出（`401 GATEWAY_AUTH_REQUIRED` / `403 GATEWAY_CSRF_INVALID` / `503 GATEWAY_INTROSPECT_UNAVAILABLE`）都必须携带 `X-Request-Id` 响应头；
  - **(b) 未挂 `gateway-auth` 的静态 / 公开路由**：例如 `/*` 的 frontend 静态分发、`/gateway/live` / `/gateway/ready` 健康路由、`/api/v1/auth/login` / `/register` / `/captcha` 等公开业务路由——全部必须携带响应头；
  - **(c) gateway 自身产生的错误响应**：upstream 连接失败的 502、readiness 失败的 `503 GATEWAY_NOT_READY`、被 `limit-count` 拒绝的 429 等——全部必须携带响应头。
- 业务服务**禁止**主动写 `X-Request-Id` 响应头（见 [`./backend.md §5`](./backend.md) 的负面契约）——否则会与 gateway 值漂移，"同一请求在 gateway 日志与业务响应头里显示不同 id" 是跨层排障的最大噩梦。
- 两条规则合并构成**闭环**：入站头来自客户端或 gateway 补齐，出站响应头**只来自** gateway——即使 gateway 自身短路响应（如 gateway-auth 直接 `ngx.exit(500)`）也必须保证响应头被写出，不能漏。

**实现要求（Standalone YAML 形态）**：

- 在 `apisix.yaml` 的**全局 plugin** 或 `config.yaml.template` 的 `nginx_config.http_server_configuration_snippet` 里声明一条 `response-rewrite` / `serverless-post-function`，从 `ngx.ctx.request_id`（由入站阶段生成的）回填 `X-Request-Id` 响应头；**不在**任何 plugin / route 级别分别实现。
- **禁止**依赖 `gateway-auth.lua:ensure_request_id` 里调用 `ngx.header["X-Request-Id"] = ...` 作为**唯一**的写入点——该写入只在 `gateway-auth` 挂载的路由上触发，(b) / (c) 两类响应会漏掉响应头。该函数内的 `ngx.header` 写入保留为请求链路内部的"早期一致性"副作用（给后续 Lua 代码即时可读），但**不作为出站响应的唯一写入点**。
- `scripts/smoke.sh` 必须包含断言：`curl -D- gateway 的 /`（frontend 静态路由）的响应必须携带 `X-Request-Id`；同样断言 `curl -D- gateway 的 /api/v1/some-nonexistent-route` 的 404 响应也必须携带。两条断言覆盖 (b) / (c) 两类形态。
- 迁移约束：本硬规则的机械落地点是 [`./gateway.md §1.2`](./gateway.md) 描述的 Standalone YAML 切换 PR——`response-rewrite` 全局声明随该 PR 一次性落下，**不保留"先在 gateway-auth.lua 里写、后补全局 response-rewrite"的中间态**。

### 8.2 结构化日志字段（与后端服务对齐）

下列字段名与 `backend.md §10.1` 保持**完全一致**，便于跨服务聚合。

| 字段 | 来源 | 语义 |
|---|---|---|
| `requestId` | gateway 补齐 | 链路 id |
| `method` / `uri` / `status` | access log | 基础 HTTP |
| `upstream` | route | 目标 upstream id |
| `userId` | `X-Auth-User-Id` | 已认证用户；未认证为空 |
| `sessionId` | `X-Auth-Session-Id` | 已认证会话；未认证为空 |
| `authResult` | gateway-auth | `ok` / `missing_token` / `introspect_failed` / `csrf_failed` |
| `elapsedMs` | access log | 处理耗时，毫秒（与业务服务字段名一致） |
| `service` | 固定值 | `"gateway"`（与业务服务字段名一致） |

### 8.3 核心告警指标

- `gateway_auth_introspect_failure_total`（introspect 调用失败）
- `gateway_auth_csrf_failure_total`（CSRF 校验失败）
- `gateway_5xx_total`（所有 5xx）
- `gateway_upstream_timeout_total{upstream=...}`（按 upstream 维度）
- SSE 路由：`active_sse_connections{route=...}`

---

## 8.4 降级模式契约（gateway 视角）

系统中任一关键组件不可用时，gateway 应返回什么、前端应据此做什么——本节用契约形式固化，避免"每个故障场景临时决定怎么降级"带来的响应漂移。前端对应消费逻辑见 [`./frontend.md`](./frontend.md) 的错误兜底节（与本节一一对应维护）。

| 故障场景 | gateway 返回 | `errorCode` | `category` | 前端期望行为 |
|---|---|---|---|---|
| `auth-service` 整体宕机（introspect 超时/连接失败） | `503` | `GATEWAY_INTROSPECT_UNAVAILABLE` | `UPSTREAM` | **保持当前页**、显示可重试 toast；**不跳登录**（避免 reload 循环） |
| `assistant-service` 整体宕机 | `502` / `503`（按 upstream 健康探测结果） | 业务服务本应发出的 `ANALYSIS_*` / `CONVERSATION_*` 错误码（若服务根本不响应，gateway 以 upstream 连接失败角度返 `502`，不假装是业务错误） | `UPSTREAM` | 当前受影响页降级（分析不可用 / 对话不可用），其他页照常 |
| `pixels_analysis` 数据库宕机、`pixels_auth` 活着 | 由 `assistant-service` 返 `503 + ANALYSIS_DATABASE_UNAVAILABLE`（见 `backend.md §8.5`） | `ANALYSIS_DATABASE_UNAVAILABLE` | `UPSTREAM` | 登录仍可用、历史查看不受影响；分析 / 新建对话等写路径降级为"历史数据暂不可用"提示 |
| `pixels_auth` 数据库宕机 | introspect 会失败 → gateway 走第 1 条路径（`503 + GATEWAY_INTROSPECT_UNAVAILABLE`） | 同第 1 条 | `UPSTREAM` | 前端视作"基础设施暂时不可用"，保持当前页 |
| LLM API 不可用（外部依赖） | `assistant-service` 返 `503 + ANALYSIS_UPSTREAM_UNAVAILABLE`（见 `backend.md §8.5`） | `ANALYSIS_UPSTREAM_UNAVAILABLE` | `UPSTREAM` | analysis 页降级、其他页（conversation 历史浏览、semantic 管理）**不受影响** |
| gateway 自身宕机 | 浏览器端表现为 nginx 层 502 或连接拒绝 | — | — | frontend 容器的 nginx 静态 502 页面或 SPA 离线缓存承担；**不依赖**任何业务降级契约 |

**硬规则**：

- **`GATEWAY_INTROSPECT_UNAVAILABLE` 必须映射到 `UPSTREAM`**（不是 `AUTH`）——用户体验上这不是"认证问题"，是"基础设施瞬时不可用"。若误映射到 `AUTH`，前端会执行"跳登录"的兜底，用户会被反复踢回登录页 → 登录还是会因 introspect 不可用失败 → 陷入循环。
- 所有"DB / LLM / 外部依赖不可用"场景**必须**映射 `category=UPSTREAM`（见 `backend.md §6.0`），让前端走可重试 UX 而不是跳登录或 5xx 通用兜底。
- 本表中新增错误码（如 `ANALYSIS_DATABASE_UNAVAILABLE` / `ANALYSIS_UPSTREAM_UNAVAILABLE`）的实现属于各业务服务的职责，在对应服务的 OpenAPI `details.errorCode` enum 和 `shared/types/<service>/ErrorCode.ts` 同步扩枚举值（见 `backend.md §6.3.2`）。**gateway 本身不发明这些错误码**；gateway 只负责"upstream 不可达"时回自己的 `GATEWAY_*` 码。

---

## 9. 显式约束：什么**不要做**

为了守住网关的职责与最小依赖，以下事项在可预见未来都不做；出现在 PR 里需要 justify：

- **不引入 etcd / Admin API / APISIX Dashboard**。
- **不引入 `gateway-bootstrap` 之类的一次性配置注入容器**。
- **不在 `apisix.yaml` 之外写路由**（禁止运行时通过任何渠道动态加路由）。
- **不在 `gateway-auth` 里新增 Bearer 分支或其他身份形态**。
- **不让网关查业务库、执行业务规则、理解业务 schema**。
- **不让后端服务各自实现 CORS、JWT 解析、CSRF 校验**——这三件事网关已做。
- **不让 `/gateway/live` 依赖任何 upstream**。
- **不把 `INTERNAL_INTROSPECTION_SECRET`、`APISIX_ADMIN_API_KEY` 等任何 secret 的默认占位值带进非开发环境**——启动期硬校验必须在占位值（如 `change-me`）或空值时 fail fast。
- **不引入 OPA / 外部策略引擎**（在出现真实复杂策略需求之前）。

---

## 10. 常见问题的判定

### 10.1 "某个业务判断到底应该放网关还是服务？"

按 §3 的四层表。如果仍不确定，自问：
- "这个判断需不需要看业务数据库的业务字段？" → 需要 = 业务服务；不需要 = 网关可以做。
- "这个判断的规则会不会随业务版本变？" → 会 = 业务服务（避免每次都发网关版）；不会 = 网关可以做。

### 10.2 "要不要把新路由做成运行时可改？"

不要。如果产品明确需要运行时灰度，回来升级本文档再说，不要用"为了未来"的理由提前引入 etcd。

### 10.3 "SSE 路由怎么配？"

- `read` 超时设极长或 0。
- 在 route 上禁用 `proxy-buffering`（或通过 `response-rewrite` 插件的相关选项）。
- 独立 `limit-count`，按 `X-Auth-User-Id` 限每人并发连接数。
- 不要把 SSE 路由和普通 REST 路由共享 `limit-req` 计数。

### 10.4 "CORS 要不要加在服务上以防万一？"

不要。双份 CORS 是下一次事故的源头。服务只对局域网内部开放（由网络策略/compose expose 保证），浏览器永远不直连服务。

---

## 11. 参考

- 前端开发指南：[`./frontend.md`](./frontend.md)
- 后端接入契约：[`./backend.md`](./backend.md)
