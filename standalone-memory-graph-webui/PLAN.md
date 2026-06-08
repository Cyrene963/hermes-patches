# Memory Graph — Nocturne Memory 复刻计划

## 目标
复刻 Nocturne Memory 原版所有功能，保留我们已有的多用户隔离机制（session auth + namespace per user）。

## 差异适配
| 原版 | 我们 | 处理方式 |
|------|------|----------|
| SQLite + aiosqlite | PostgreSQL + asyncpg | 改 DB URL，SQLAlchemy 兼容 |
| Bearer Token auth | Session cookie + bcrypt | 保留我们的 auth.py，加到中间件 |
| config.json 配置 | 环境变量 + 硬编码 | 加 config.py |
| 单 namespace | 多用户 namespace | 保留我们的隔离 |
| 无 MCP | MCP server | 后续添加 |

## Phase 1: 后端 (Priority order)

### 1.1 项目结构
```
standalone-memory-graph-webui/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── config.py             # 配置管理
│   ├── auth.py               # Session auth (保留我们的)
│   ├── namespace_middleware.py
│   ├── health.py
│   ├── text_patch.py
│   ├── system_views.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py         # SQLAlchemy ORM
│   │   ├── database.py       # DB manager
│   │   ├── graph.py          # GraphService
│   │   ├── glossary.py       # GlossaryService
│   │   ├── search.py         # SearchIndexer
│   │   ├── search_terms.py
│   │   ├── snapshot.py       # ChangesetStore
│   │   └── namespace.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── browse.py
│   │   ├── review.py
│   │   ├── maintenance.py
│   │   ├── settings.py
│   │   └── utils.py
│   └── models/
│       ├── __init__.py
│       └── schemas.py
├── frontend/                  # React app (Phase 2)
└── deploy/
```

### 1.2 从原版复制并适配的文件
1. models.py — 改 postgres 兼容
2. database.py — 改 asyncpg engine
3. graph.py — 完整复制
4. glossary.py — 完整复制
5. search.py — 完整复制
6. snapshot.py — 完整复制
7. api/browse.py — 完整复制
8. api/review.py — 完整复制
9. api/maintenance.py — 完整复制
10. api/settings.py — 适配我们的配置
11. text_patch.py — 完整复制
12. system_views.py — 完整复制
13. namespace_middleware.py — 适配我们的 session auth

### 1.3 Auth 适配
原版用 Bearer token，我们用 session cookie。改造方式：
- 保留我们的 auth.py (bcrypt + session cookie)
- 在 namespace_middleware 中从 session 获取 user namespace
- Admin 用户可以切换 namespace（通过 X-Namespace header）

## Phase 2: 前端

### 2.1 复制原版 React 代码
- App.jsx + routes
- ReviewPage + DiffViewer + SnapshotList
- MemoryBrowser + 所有子组件
- MaintenancePage
- SettingsDrawer
- api.js (改 auth 从 token → cookie)

### 2.2 适配
- TokenAuth → 我们的登录页
- Axios interceptor → 不需要 Bearer，用 cookie
- Namespace selector → 保留

## Phase 3: 部署
- 前端 build → Nginx 静态文件
- 后端 → PM2 or systemd
- Nginx reverse proxy
