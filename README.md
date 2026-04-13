# pixels-rover
The web UI of Pixels — a modern frontend-backend separated architecture.

Watch the demonstration video:
[![IMAGE](video/pixels-rover-720p-cover.png)](https://www.bilibili.com/video/BV1awDQYcEsN/?vd_source=da6f80d8fe2bab1291999a9535251c78)
[Download the Video](video/pixels-rover-720p.mp4)

## Architecture

- **Backend**: Spring Boot 3 + Spring Security (JWT) + Spring Data JPA + MySQL
- **Frontend**: React 18 + TypeScript + Vite + Ant Design 5 + Zustand + ECharts

The backend serves as a pure REST API (`/api/v1/**`), and the frontend is an independent SPA application.

## Quick Start

After completing the database setup (see below), use the automated startup script:

```bash
# Start both backend and frontend
./start.sh

# Start backend only
./start.sh backend

# Start frontend dev server only
./start.sh frontend

# Build frontend for production and start backend
./start.sh --prod
```

Press `Ctrl+C` to gracefully stop all services.

## Install Step-by-Step

### 1. Database Setup

Login MySQL and create a user and a `pixels_rover` database for Pixels:

```sql
CREATE USER 'pixels'@'%' IDENTIFIED BY 'password';
CREATE DATABASE pixels_rover;
GRANT ALL PRIVILEGES ON pixels_rover.* to 'pixels'@'%';
FLUSH PRIVILEGES;
```

Use `db/pixels_rover.sql` to create tables in `pixels_rover`.

### 2. Backend Configuration

Adjust the configuration in `src/main/resources/application.properties`:

```properties
# mysql
spring.datasource.username=pixels
spring.datasource.password=password

# pixels_rover port
server.port=8081

# text to sql url
text2sql.url=http://localhost/text2sql

# pixels server port
pixels.server.port=18890

# JWT (change the secret in production)
jwt.secret=cGl4ZWxzZGItcm92ZXItand0LXNlY3JldC1rZXktMjAyNC1taW5pbXVtLTI1Ni1iaXRz
jwt.access-token-expiration-ms=3600000
jwt.refresh-token-expiration-ms=604800000
```

### 3. Start the Backend

```bash
mvn spring-boot:run
```

The backend API will be available at `http://localhost:8081`.

### 4. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server will be available at `http://localhost:3000`, with API requests proxied to the backend.

### 5. Build for Production

```bash
cd frontend
npm run build
```

The production-ready static files will be generated in `frontend/dist/`.

## API Overview

| Module     | Endpoint Prefix          | Description                        |
|------------|--------------------------|------------------------------------|
| Auth       | `/api/v1/auth/*`         | Login, register, captcha, refresh  |
| Metadata   | `/api/v1/metadata/*`     | Schemas, tables, columns, views    |
| Query      | `/api/v1/query/*`        | Submit query, status, results      |
| Text-to-SQL| `/api/v1/query/text-to-sql` | Natural language to SQL         |
| Chat       | `/api/v1/chat/*`         | Chat history, SQL statements       |
