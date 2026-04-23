# Pixels Rover

Pixels Rover 是一个面向数据分析场景、但可继续扩展为更通用智能编排能力的 assistant 系统。当前仓库已经按最终态完成服务边界收口：

- `auth-service` 只负责认证、会话、JWT 签发/自校验和内部 introspection
- `assistant-service` 是唯一业务后端，当前负责分析、会话历史、语义层和后端元数据
- `gateway` 只保留显式资源前缀路由，不再承载 legacy Translator 代理
- 前端只保留 `authApi`、`conversationApi + analysis SSE`、`metadataApi(/api/v1/analysis/backends/*)` 三类调用面

## Architecture

```text
┌──────────────┐      ┌──────────────────────────────┐
│   Frontend   │─────▶│ APISIX Gateway               │
│ React + Vite │      │ :80                          │
└──────────────┘      │                              │
                      │ /api/v1/auth/*              -> auth-service
                      │ /api/v1/analysis*           -> assistant-service
                      │ /api/v1/analysis/backends*  -> assistant-service
                      │ /api/v1/conversations*      -> assistant-service
                      │ /api/v1/semantic*           -> assistant-service
                      │ /                           -> frontend
                      └──────────┬───────────┬───────────┘
                                 │           │
                                 ▼           ▼
                         ┌──────────────┐ ┌──────────────┐
                         │ auth-service │ │assistant-serv│
                         │ Spring Boot  │ │ FastAPI      │
                         │ :8081        │ │ :8090        │
                         └──────┬───────┘ └──────┬───────┘
                                │                │
                                ▼                ▼
                         ┌──────────────┐  ┌──────────────┐
                         │ pixels_auth  │  │pixels_analysis│
                         │ MySQL        │  │ MySQL        │
                         └──────────────┘  └──────────────┘
```

## Service Responsibilities

| Service | Responsibility |
|---------|----------------|
| `auth-service` | login/register/captcha/refresh/logout/session management/internal introspection |
| `assistant-service` | analysis SSE, conversation history, semantic CRUD, backend metadata browsing |
| `gateway` | explicit route dispatch, auth introspection, identity header injection, CSRF enforcement |
| `frontend` | SPA UI for login, conversation management, analysis execution, reports, schema browsing |

## Public APIs

### Auth Service

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register`
- `GET /api/v1/auth/captcha`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/user-info`
- `GET /api/v1/auth/sessions`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/logout-all`
- `DELETE /api/v1/auth/sessions/{sessionId}`
- `POST /api/internal/auth/introspect` only for gateway/internal callers

### Assistant Service

- `POST /api/v1/analysis`
- `GET /api/v1/analysis/{sessionId}`
- `POST /api/v1/conversations`
- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{threadId}`
- `PATCH /api/v1/conversations/{threadId}`
- `GET /api/v1/semantic/metrics`
- `POST /api/v1/semantic/metrics`
- `GET /api/v1/semantic/dimensions`
- `POST /api/v1/semantic/dimensions`
- `GET /api/v1/semantic/synonyms`
- `POST /api/v1/semantic/synonyms`
- `GET /api/v1/analysis/backends`
- `GET /api/v1/analysis/backends/{backendId}/schemas`
- `GET /api/v1/analysis/backends/{backendId}/schemas/{schema}/tables`
- `GET /api/v1/analysis/backends/{backendId}/schemas/{schema}/tables/{table}/columns`

### Removed Legacy APIs

These routes are intentionally removed and must not be used again:

- `/api/v1/chat/*`
- `/api/v1/query/*`
- `/api/v1/metadata/*`
- `POST /api/v1/analysis/text-to-sql`

## Quick Start

### Prerequisites

| Component | Requirement |
|-----------|-------------|
| Docker | 24+ |
| Docker Compose | v2 |

### Recommended Full-Stack Startup

The canonical local topology is the same as production: all traffic enters through the gateway.

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- App: `http://localhost`
- Gateway liveness: `http://localhost/gateway/live`
- Gateway readiness: `http://localhost/gateway/ready`
- MySQL: `localhost:3306`

### Database Layout

`db/pixels_rover.sql` initializes the final-state MySQL layout:

- `pixels_auth`: logical database owned by `auth-service`; application tables managed by Flyway migrations under `services/auth-service/src/main/resources/db/migration/`
- `pixels_analysis`: logical database owned by `assistant-service`; application tables managed by Alembic migrations under `services/assistant-service/alembic/versions/`

`db/pixels_rover.sql` only creates the logical databases + grants; it runs once on MySQL volume init. Application-table schemas live with each service and are applied on service startup (Flyway in the Spring Boot lifecycle, Alembic via the assistant-service container entrypoint). See `docs/development/backend.md §12` for the full contract.

### Environment

Root `.env` drives Docker Compose:

```env
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-your-api-key-here
MYSQL_ROOT_PASSWORD=rootpassword
MYSQL_PASSWORD=password
INTERNAL_INTROSPECTION_SECRET=change-me
```

`services/assistant-service/.env.example` already defaults to MySQL:

```env
ROVER_DATABASE_URL=mysql+aiomysql://pixels:password@localhost:3306/pixels_analysis
```

## Local Component Development

`start.sh` is useful for isolated service development, but it is not the canonical full-stack path.

```bash
./start.sh java
./start.sh python
./start.sh frontend
```

Notes:

- `frontend` dev server still proxies `/api` to `http://localhost:80`, so it expects the gateway to be running.
- `assistant-service` protected APIs trust gateway identity headers and are not meant to be called directly from the browser.
- For end-to-end auth, conversation, and analysis verification, use `docker compose up`.

## Data Ownership

### `pixels_auth`

- `user`
- `auth_session`

### `pixels_analysis`

- `conversation_threads`
- `analysis_sessions`
- `analysis_steps`
- semantic tables created by SQLAlchemy

Historical chat/query tables are removed and are not migrated.

## Project Structure

```text
pixels-rover/
├── frontend/                     # React SPA (单 Web 前端)
├── services/auth-service/        # Auth-only service
├── services/assistant-service/   # Business backend
├── gateway/                      # APISIX config and bootstrap
├── db/                           # Final-state MySQL init script
├── docs/development/             # Cross-repo specs (frontend/gateway/backend)
├── docs/design/                  # Long-lived design archives (e.g. jwt-rotation)
├── docs/runbooks/                # Operational runbooks
└── .notes/                       # Working todo / temporary plans (engineering-design / todolist / paper-outline); not for long-term reference
```

## Related Docs

开发规范（权威）：

- [前端开发指南](docs/development/frontend.md)
- [网关开发指南](docs/development/gateway.md)
- [后端接入契约](docs/development/backend.md)

长期设计沿革（对外公开，随仓库发布）：

- [JWT 非对称签名与密钥轮换设计](docs/design/jwt-rotation.md)（配套实施 Runbook 见下）

运维 Runbook：

- [JWT RS256 切换与密钥轮换 Runbook](docs/runbooks/jwt-rotation-drill.md)
