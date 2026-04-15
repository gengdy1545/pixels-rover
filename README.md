# Pixels Rover

Pixels Rover — 基于 LLM 的智能数据分析系统，自动将自然语言问题转化为多步查询计划并生成分析结论。

Watch the demonstration video:
[![IMAGE](video/pixels-rover-720p-cover.png)](https://www.bilibili.com/video/BV1awDQYcEsN/?vd_source=da6f80d8fe2bab1291999a9535251c78)
[Download the Video](video/pixels-rover-720p.mp4)

## Architecture

```
┌──────────────┐      ┌──────────────────┐      ┌──────────────────┐
│   Frontend   │─────▶│  Java Backend    │      │  Python Backend  │
│  React 18    │      │  Spring Boot 3   │      │  FastAPI         │
│  :3000       │─────▶│  :8081 (auth)    │      │  :8090 (analysis)│
└──────────────┘      └──────────────────┘      └──────────────────┘
                              │                         │
                              ▼                         ▼
                         ┌─────────┐             ┌────────────┐
                         │  MySQL  │             │  DuckDB /  │
                         │  (auth) │             │  Pixels DB │
                         └─────────┘             └────────────┘
```

- **Java Backend** (Spring Boot 3): 认证服务 — JWT 登录、注册、验证码、Token 刷新
- **Python Backend** (FastAPI): 智能分析引擎 — 任务理解、语义解析、查询规划、SQL 执行、结论生成
- **Frontend** (React 18 + TypeScript + Vite + Ant Design 5): 智能分析交互界面，实时 SSE 流式展示分析进度

## Quick Start

### Prerequisites

| Component | Requirement |
|-----------|-------------|
| Java      | JDK 17+    |
| Maven     | 3.8+       |
| Python    | 3.10+      |
| Node.js   | 18+        |
| npm       | 9+         |
| MySQL     | 8.0+       |

### One-command startup

```bash
# Start all three services (Java + Python + Frontend)
./start.sh

# Start individual services
./start.sh java        # Java backend only (auth, :8081)
./start.sh python      # Python backend only (analysis, :8090)
./start.sh frontend    # Frontend dev server only (:3000)

# Production build
./start.sh --prod
```

Press `Ctrl+C` to gracefully stop all services.

默认情况下，`./start.sh` 启动 Java 或 Python 服务时会自动在 `.tmp/jwt-keys/` 下生成开发用 RSA 密钥，并让本地联调默认跑在 `RS256 + kid` 模式。如果你已经通过环境变量提供了 JWT 密钥配置，启动脚本会优先使用外部配置。

## Step-by-Step Setup

### 1. Database Setup

Login MySQL and create the `pixels_rover` database:

```sql
CREATE USER 'pixels'@'%' IDENTIFIED BY 'password';
CREATE DATABASE pixels_rover;
GRANT ALL PRIVILEGES ON pixels_rover.* TO 'pixels'@'%';
FLUSH PRIVILEGES;
```

Use `db/pixels_rover.sql` to create tables in `pixels_rover`.

### 2. Java Backend Configuration

Adjust `services/auth-service/src/main/resources/application.properties`:

```properties
spring.datasource.username=pixels
spring.datasource.password=password
server.port=8081
text2sql.url=http://localhost/text2sql
pixels.server.port=18890
jwt.secret=cGl4ZWxzZGItcm92ZXItand0LXNlY3JldC1rZXktMjAyNC1taW5pbXVtLTI1Ni1iaXRz
```

如果你要手动切到 RSA，可参考 [docs/jwt-rs256-cutover.md](docs/jwt-rs256-cutover.md) 和 `scripts/generate-jwt-rsa-keys.sh`。

Start:

```bash
cd services/auth-service
mvn spring-boot:run
```

### 3. Python Backend Configuration

```bash
cd services/analysis-service
cp .env.example .env
```

Edit `services/analysis-service/.env` with your LLM API key and other settings:

```env
ROVER_LLM_MODEL=gpt-4o-mini
ROVER_LLM_API_KEY=sk-your-api-key-here
ROVER_DATABASE_URL=sqlite+aiosqlite:///./rover.db
ROVER_DUCKDB_PATH=:memory:
```

Start:

```bash
cd services/analysis-service
./run.sh
```

The Python backend will be available at `http://localhost:8090`.

### 4. Frontend

```bash
cd apps/frontend
npm install
npm run dev
```

The frontend dev server runs at `http://localhost:3000`:
- `/api/v1/auth/*` requests are proxied to the Java backend (:8081)
- All other `/api/*` requests are proxied to the Python backend (:8090)

### 5. Production Build

```bash
cd apps/frontend
npm run build
```

Output: `apps/frontend/dist/`

## API Overview

### Java Backend (:8081) — Authentication

| Endpoint              | Description               |
|-----------------------|---------------------------|
| `POST /api/v1/auth/login`    | Login with captcha  |
| `POST /api/v1/auth/register` | Register new user   |
| `GET  /api/v1/auth/captcha`  | Get captcha image   |
| `POST /api/v1/auth/refresh`  | Refresh JWT tokens  |
| `GET  /api/v1/auth/user`     | Get current user    |

### Python Backend (:8090) — Intelligent Analysis

| Endpoint                           | Description                         |
|------------------------------------|-------------------------------------|
| `POST /api/v1/analysis`           | Submit question (SSE stream response) |
| `GET  /api/v1/analysis/{id}`      | Get completed analysis result        |
| `GET  /api/v1/backends`           | List registered storage backends     |
| `GET  /api/v1/backends/{id}/schemas` | List schemas in a backend         |
| `GET  /api/v1/backends/{id}/schemas/{s}/tables` | List tables         |
| `GET  /api/v1/backends/{id}/schemas/{s}/tables/{t}/columns` | List columns |
| `GET  /api/v1/semantic/metrics`   | List semantic metrics                |
| `GET  /api/v1/semantic/dimensions`| List semantic dimensions             |

## Project Structure

```
pixels-rover/
├── apps/
│   └── frontend/           # React frontend
│       └── src/
│           ├── pages/      #   Analysis, Reports, Login, Register
│           ├── components/ #   AnalysisInput, TaskCard, PlanTimeline, StepDetail, SummaryCard, ...
│           ├── stores/     #   Zustand stores (analysis, schema, auth)
│           ├── services/   #   API clients (analysisApi, metadataApi, authApi)
│           └── types/      #   TypeScript type definitions
├── services/
│   ├── auth-service/       # Java backend (Spring Boot — auth only)
│   │   ├── pom.xml
│   │   └── src/main/java/
│   └── analysis-service/   # Python backend (FastAPI — analysis engine)
│       ├── app/
│       │   ├── api/        #   API routes (analysis, backends, semantic)
│       │   ├── core/       #   Core modules (harness, interpreter, planner, executor, ...)
│       │   ├── models/     #   SQLAlchemy ORM models
│       │   ├── schemas/    #   Pydantic data contracts
│       │   ├── services/   #   Orchestration service
│       │   └── storage/    #   Storage backend abstraction (DuckDB, Pixels)
│       ├── .env.example
│       ├── pyproject.toml
│       └── run.sh
├── docs/                   # Design documents
├── start.sh                # Unified startup script
└── db/                     # Database initialization scripts
```
