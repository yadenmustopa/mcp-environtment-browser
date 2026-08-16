# Tahapan Implementasi — mcp-env-browser Phase 1

> **Spec v3 protocol**: File ini lazy-materialized saat spec mendekati closure.
> Digunakan untuk record detail eksekusi per phase + transition notes.
>
> **Status (2026-08-16)**: Pre-archive skeleton — semua 9 phase sudah completed.
> File ini akan di-archive ke `docs/archive/01_phase1_local_first_license_only_YYYY-MM-DD/`
> setelah owner executes Tahap B (5 manual checks) per `docs/OWNER_EXECUTION_GUIDE.md`.

---

## Ringkasan Eksekusi

**Tanggal mulai**: 2026-08-16
**Tanggal code-complete**: 2026-08-16 (single-day session, 9 phase closed)
**Total logical commits**: 23 (sejak Phase 1 bootstrap)
**Owner manual validation**: pending (5 checks B1-B5)

## Timeline Per Phase

| Phase | Commit | Status | Key Files |
|---|---|---|---|
| 1. Bootstrap | `9bdd5b8` (+ `c9b6955`) | ✅ | `pyproject.toml`, `install.sh`, skeleton |
| 2. License Server | `746a45e` | ✅ | `src/license_server/{db,server,api/*}.py` (4 endpoints + atomic increment) |
| 3. Vault Backend | `e37c6be` | ✅ | `src/mcp_env_browser/vault/{secretstorage,encrypted_json}.py` (2 backends) |
| 4. License Client | `b05fe86` | ✅ | `src/mcp_env_browser/license/__init__.py` (HTTP wrapper + config loader) |
| 5. Browser Executor | `1d3830c` | ✅ | `src/mcp_env_browser/browser/__init__.py` (12 actions + pause/resume) |
| 6. MCP Server | `2a5935c` + `61358fc` | ✅ | `src/mcp_env_browser/mcp_server.py` (13 tools + 3 prompts) + `browser/cdp.py` |
| 7. Web Monitoring | `ec06114` | ✅ | `src/mcp_env_browser/monitor.{py,html}` (FastAPI + vanilla JS) |
| 8. CLI Distribution | `32268e5` | ✅ | `src/mcp_env_browser/cli.py` (5 subcommands) |
| 9. Hermes E2E | `4b1b4ff` + `b8fd481` | ✅ | `tests/manual/test_hermes_e2e.py` (4/4 auto smoke) |
| Audit compliance | `31f5343` + `15ed908` | ✅ | scopes/context/clip args + README/install.sh sync |

## Phase Detail Logs

### Phase 1 — Bootstrap

**Goal**: Project skeleton, install script, editable build.

**Files**:
- `pyproject.toml` — Python 3.10+, MIT, FastAPI/Click/Playwright stack
- `install.sh` — 5-step idempotent installer (Python detect → venv → pip install → Playwright Chromium → verify)

**Notes**:
- install.sh originally assumed Phase 8-only implementation → fixed during Phase 9 E2E (commit `15ed908`) to reflect actual Phase 1 COMPLETE state
- `pyproject.toml` pinned `fastapi>=0.115` (main dep, not [server] extra) because `monitor.py` imports FastAPI at module level + mcp's sse-starlette requires starlette>=1.0 which breaks fastapi<0.115

### Phase 2 — License Server

**Goal**: FastAPI server dengan 4 endpoints + atomic per-tab counter.

**Endpoints**:
- `POST /license/register` (admin token) — register new user
- `POST /license/check` — validate API key
- `POST /tab/increment` — atomic counter (SQLite `BEGIN IMMEDIATE`)
- `GET /health` — health check

**Atomic guarantee**:
- 20 threads × 50 increments = 1000 (perfect atomic, no race)
- `db.py:259-263` — `BEGIN IMMEDIATE` then check quota before UPDATE

**Tests**: 33 unit + integration

### Phase 3 — Vault Backend

**Goal**: Credential storage dengan 2 backend (libsecret + encrypted JSON).

**Implementations**:
- `SecretStorageBackend` — Linux libsecret via `secretstorage` Python lib
- `EncryptedJSONBackend` — AES-GCM + scrypt KDF fallback for headless

**Lazy import via PEP 562** (`__getattr__` di `vault/__init__.py`) — avoid loading libsecret unless used.

**Tests**: 19 unit

### Phase 4 — License Client

**Goal**: HTTP wrapper untuk license server endpoints.

**Methods**:
- `LicenseClient.check()` → POST `/license/check`
- `LicenseClient.increment(amount)` → POST `/tab/increment`
- `load_config()` — read `~/.config/mcp-env-browser/config.json` + env var overrides

**Config schema**: `license_server_url`, `license_api_key`, `vault_backend`, `browser_headless`, `log_level`

**Tests**: 18 unit (5 scenarios: 200/401/403/429/network)

### Phase 5 — Browser Executor

**Goal**: Playwright wrapper + per-tab counter hook + pause/resume.

**Public methods**:
- `connect(target, credential_key, label?)` — full flow: vault → license check → increment → new_page → goto
- `list_sessions(include_screenshot?)` — sorted by position left-to-right
- `focus_session(session_id)` — `page.bring_to_front()`
- `close(session_id?)` — single or all
- `pause_session(reason)` + `resume_session()` — user-replacement pattern
- `action(session_id, action, **kwargs)` — dispatch 12 sub-actions

**Action list** (spec §6.4): `navigate | click | type | scroll | drag | hover | screenshot | wait_for_selector | wait_for_navigation | evaluate | select_option | press_key`

**Type action**: realistic typing 50±20ms random jitter per char

**Tests**: 44 unit (Playwright mocked via `sys.modules` injection)

### Phase 6 — MCP Server

**Goal**: Expose 13 tools + 3 prompts via MCP stdio.

**13 Tools**: per spec §6.4
- 4 credential: list / get_meta / set / delete
- 6 browser: connect / list_sessions / close / action / pause / resume
- 3 CDP: console_log / network_log / inspect

**3 Prompts**: per spec §6.4.1
- `oauth_confirmation_flow(service, scopes?)` — re-auth pattern
- `browser_debug_workflow(symptom, service?)` — 4-step investigation
- `human_intervention_workflow(challenge_type, context?)` — pause/resume pattern

**Async pattern**: `asyncio.to_thread` wraps sync BrowserExecutor/vault methods

**Security**: `smart_get_credential_meta` NEVER returns password/value/token (only metadata)

**Tests**: 37 mcp_server + 10 cdp = 47 unit

### Phase 7 — Web Monitoring

**Goal**: FastAPI + vanilla JS polling UI di localhost:9876.

**Endpoints**: `GET /`, `GET /api/sessions`, `POST /api/sessions/{id}/focus`, `GET /health`

**Polling**: 2s (vanilla JS, no framework per spec §6.6.1 KISS principle)

**Status colors**: ACTIVE (green) / PAUSED (yellow) / CAPTCHA (red) / ERROR (gray)

**Tests**: 8 unit (100% coverage)

### Phase 8 — CLI Distribution

**Goal**: Click CLI dengan 5 subcommands.

**Subcommands**: `version`, `config show/path/set-*`, `init`, `serve`, `doctor`

**Logging**: structlog → stderr + `~/.local/share/mcp-env-browser/logs/{date}.log`

**Config**: `~/.config/mcp-env-browser/config.json` (chmod 600 POSIX)

**Tests**: 12 unit (CliRunner)

### Phase 9 — Hermes E2E Validation

**Goal**: Smoke test MCP stdio JSON-RPC round-trip tanpa real browser.

**Auto smoke** (`tests/manual/test_hermes_e2e.py`):
- ✅ CLI --version
- ✅ version subcommand
- ✅ tools/list returns 13 tools
- ✅ prompts/list returns 3 prompts

**Manual checks** (5 per spec §9, see `docs/OWNER_EXECUTION_GUIDE.md`):
- B1: init wizard
- B2: serve + Chromium
- B3: counter di SQLite DB
- B4: license gate invalid key
- B5: pause/resume CAPTCHA

## Cross-Phase Decisions (K1-K7)

Per `refactor/90_decisions_log.md` (CAPTURE — jangan diedit):

| ID | Lock |
|---|---|
| K1 | Per-tab = `browser.new_page()` / new CDP target = 1 tab |
| K2 | Credential & browser = **local** (no server weight) |
| K3 | Subscription tiers: dashboard deferred; Phase 1 dev/free + popOS server |
| K4 | Anti-piracy: license gate + business model (K5) |
| K5 | Protected layer: PyInstaller binary distribution (Phase 2) |
| K6 | Counter sync: real-time per-tab hit server; unregistered user = no access |
| K7 | Hardware-bound key: not for Phase 1; simple first |

## Honest Risk Register (per spec §8)

| Risiko | Status Saat Phase 1 Close |
|---|---|
| Server down = agent total stop | Accepted per K6 (Phase 2: offline mode) |
| User bypass HTTP | Accepted (Phase 2: counter batch sync + anomaly alert) |
| libsecret unavailable di Win/Mac | Out of scope (Phase 1 Linux-only) |
| MCP stdio flaky | mitigated via reconnect + clear errors |
| Credential bocor via agent log | **PROTECTED**: vault NEVER returns plaintext to agent |

## Test Summary (sampai code-complete 2026-08-16)

| Suite | Tests | Coverage |
|---|---|---|
| `tests/unit/test_browser_executor.py` | 45 | 91% |
| `tests/unit/test_browser_cdp.py` | 10 | 95% |
| `tests/unit/test_mcp_server.py` | 37 | 96% |
| `tests/unit/test_monitor.py` | 8 | 100% |
| `tests/unit/test_cli.py` | 12 | 73% |
| `tests/unit/test_license_client.py` | 18 | 91% |
| `tests/unit/test_license_db.py` | 33 | 95% |
| `tests/unit/test_vault_secretstorage.py` | 13 (1 skip) | 69% |
| `tests/unit/test_vault_encrypted_json.py` | 7 | 89% |
| `tests/integration/test_license_server.py` | (covered above) | — |
| `tests/manual/test_hermes_e2e.py` | 4 smoke | manual |
| **TOTAL** | **183 + 1 skip** | **87.29%** |

## What Remains (Phase 2)

Per `docs/spec/01_phase1_local_first_license_only/roadmap_migration.md`:

1. **Strategi D**: credential vault moves to server (master key server-side)
2. **Multi-tenant isolation** (100+ user base trigger)
3. **Dashboard Vite + Svelte + Routify + Tailwind** (Phase 1 monitoring → full dashboard)
4. **Per-target rate limit** (validate demand first)
5. **Stripe / billing integration** (subscription tier trigger)
6. **Cross-platform vault** (Windows + macOS)
7. **PyInstaller binary build** (deferred from Phase 1, ~50MB binary + 150MB Chromium)
8. **SSE streaming monitor** (replace polling 2s with real-time events)
