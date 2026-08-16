# 20 — License Server Spec (Remote)

> Detail teknis untuk `src/license_server/`.

---

## Module Map

```
src/license_server/
├── __init__.py
├── server.py              # FastAPI app + lifespan
├── db.py                  # SQLite + migrations + repositories
└── api/
    ├── __init__.py        # router aggregator
    ├── health.py          # GET /health
    ├── license.py         # POST /license/check, POST /license/register
    └── tab.py             # POST /tab/increment
```

---

## Endpoints

### `GET /health`

**Auth**: none
**Returns**:
```json
{"status": "ok", "version": "0.1.0"}
```

---

### `POST /license/check`

**Auth**: API key in body (Phase 1) / Bearer token (Phase 2)
**Body**:
```json
{"api_key": "hex_32_chars"}
```

**Returns (200)**:
```json
{
  "valid": true,
  "plan": "dev",
  "tabs_used": 42,
  "tabs_quota": 10000,
  "expires_at": "2027-01-01T00:00:00Z"
}
```

**Returns (401)** — invalid API key:
```json
{"detail": "invalid api key"}
```

**Returns (403)** — expired subscription:
```json
{"detail": "subscription expired"}
```

**Returns (429)** — quota exceeded:
```json
{"detail": "tab quota exceeded", "tabs_used": 10000, "tabs_quota": 10000}
```

---

### `POST /tab/increment`

**Auth**: API key in body
**Body**:
```json
{"api_key": "hex_32_chars", "amount": 1}
```

**Returns (200)**:
```json
{
  "ok": true,
  "tabs_used": 43,
  "tabs_quota_remaining": 9957
}
```

**Returns (429)** — quota exceeded (atomic check):
```json
{"detail": "tab quota exceeded", "tabs_used": 10000, "tabs_quota": 10000}
```

**Atomic**: SQLite transaction dengan `SELECT ... FOR UPDATE`-equivalent
(`BEGIN IMMEDIATE`).

---

### `POST /license/register`

**Auth**: admin token (Phase 1: env var `ADMIN_TOKEN`)
**Body**:
```json
{"email": "alice@example.com", "plan": "dev", "tabs_quota": 10000, "expires_in_days": 365}
```

**Returns (200)**:
```json
{"api_key": "generated_hex_32", "email": "...", "plan": "dev"}
```

**Phase 1**: tidak ada admin UI. Owner run manual via curl.

---

## Database Schema

```sql
-- users
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  api_key TEXT UNIQUE NOT NULL,
  plan TEXT NOT NULL DEFAULT 'dev',
  tabs_quota INTEGER NOT NULL DEFAULT 10000,
  tabs_used INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_users_api_key ON users(api_key);
CREATE INDEX idx_users_email ON users(email);

-- tab_events (audit log)
CREATE TABLE tab_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  tabs INTEGER NOT NULL,
  source TEXT,  -- optional: which MCP call triggered
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX idx_tab_events_user_id_created ON tab_events(user_id, created_at);

-- alembic_version (migration tracking)
CREATE TABLE alembic_version (
  version_num TEXT NOT NULL
);
```

**Migrations**: pakai `alembic` standard (atau manual SQL untuk Phase 1 simplicity).

---

## Deployment (Phase 1 — Owner popOS)

```bash
# Install
cd /mnt/nvme/my-job/github/yadenmustopa/mcp-environtment-browser
pip install -e ".[server]"
mcp-env-browser-license-server init  # create DB + first admin user
mcp-env-browser-license-server serve --port 8765
```

**Run as background**: systemd user service atau `nohup` (sederhana).

```ini
# ~/.config/systemd/user/mcp-env-browser-license.service
[Unit]
Description=mcp-env-browser license server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/denevill
ExecStart=/home/denevill/.local/bin/mcp-env-browser-license-server serve --port 8765
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable mcp-env-browser-license.service
systemctl --user start mcp-env-browser-license.service
```

---

## Phase 2 Changes (Capture untuk Agent Masa Depan)

- Switch dari API key body ke `Authorization: Bearer <jwt>`
- JWT signed dengan server secret, expire 1 jam
- Refresh token endpoint
- Multi-tenant isolation (user_id di setiap query)
- Distributed rate limit (Redis)
- TLS wajib (Let's Encrypt + reverse proxy)

---

## Phase 3 Changes

- Stripe webhook handler untuk auto-renewal
- Per-target rate limit (e.g., tiktok.com 1000/bulan, github.com unlimited)
- Audit log retention policy (90 hari hot, 1 tahun cold storage)
- Admin dashboard API (CRUD users, view usage, manual override)

---

## Testing Strategy

- **Unit**: repository functions, atomic counter increment
- **Integration**: FastAPI TestClient, 100 concurrent increment simulation
- **Load**: `locust` simulation 1000 tabs/detik (Phase 2)
- **Manual**: owner curl test semua endpoint

---

## Security Notes

- **API key generation**: `secrets.token_hex(32)` (256-bit entropy)
- **DB file permission**: `chmod 600` (owner only)
- **CORS**: disabled (server-to-server only)
- **Rate limit per IP**: simple in-memory counter, 100 req/min (Phase 2: Redis)
- **HTTPS**: Phase 1 pakai HTTP (localhost only). Phase 2 wajib HTTPS