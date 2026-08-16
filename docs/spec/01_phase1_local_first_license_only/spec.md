# Spec #01 — Phase 1: Local-First + License Server Only

**Slug:** `01_phase1_local_first_license_only`
**Dibuat:** 2026-08-16
**Status:** `planning` (DRAFT — belum implementasi)
**Area:** `be`, `fe`, `docs`, `ops`
**Owner:** yadenmustopa

---

## 1. Latar Belakang & Problem Statement

Agent LLM modern (Hermes, OpenAI, Claude Code, dll) punya keterbatasan saat
harus berurusan dengan credential. Masalah nyata:

1. **Username/password/SSH key/OAuth token/env var** harus dimasukkan ke
   context agent — rentan, terekspos di log/UI/chat history
2. **Agent tidak portable** — kalau agent di-restart atau pindah host,
   credential harus dimasukkan ulang
3. **Tidak ada browser DevTools access** — kalau hanya capture atau kode saja,
   agent terbatas dan akan buat asumsi
4. **Tidak ada interactive confirmation** — kalau OAuth perlu re-auth atau
   credential tidak ada, agent diam-diam return error

**Goal produk**: Sebuah MCP server yang:
- Menyimpan credential terenkripsi di local user (bukan di agent context)
- Saat agent perlu eksekusi browser (scrape TikTok, akses GCP, login Coretax),
  MCP yang handle login + ambil data + return JSON
- License-based subscription per-tab (per `browser.new_page()`)
- Multi-agent: agent apapun yang connect MCP bisa pakai

**Repositori target** (use case awal):
- TikTok (scrape akun)
- Google (Gmail/Drive/Sheets via OAuth)
- GCP (service account, project access)
- Coretax DJP (login + ambil data pajak)
- "berbagai bidang lain" — extensible

---

## 2. Klarifikasi Diskusi (Capture K1-K7)

Detail lengkap ada di `refactor/90_decisions_log.md`. Ringkasan:

| ID | Pertanyaan | Keputusan |
|---|---|---|
| K1 | Per-tab = metrik apa? | Setiap `browser.new_page()` / new CDP target = 1 tab |
| K2 | Credential & browser di mana? | **Local** — tidak berat di server |
| K3 | Subscription tiers? | **Dashboard** nanti. Fase 1: dev/free, install server di popOS user |
| K4 | Anti-piracy strategi? | Kode di server (Strategi A: license DB only) — K5 diperdalam di bawah |
| K5 | "Kode penting" yang dilindungi | Kode MCP utama agar tidak ditiru/copy — dipenuhi via distribusi binary (PyInstaller) + license gate |
| K6 | Counter sync model | Real-time per-tab hit server. User tidak terdaftar = fitur tidak bisa dipakai |
| K7 | Hardware-bound key | **Tidak untuk phase awal**. Phase awal simple dulu, migrasi ke server sebenarnya nanti |

---

## 3. Tujuan Phase 1

1. **MCP server (client-side)** yang expose tools untuk:
   - `smart_connect_browser(target, credential_key, label?)` — buka browser,
     login pakai credential dari vault, return session dengan label untuk
     multi-tab clarity
   - `smart_get_credential(key)` — ambil credential dari vault (auto-decrypt,
     tidak pernah return plaintext ke agent)
   - `smart_set_credential(key, value, type)` — simpan credential baru ke vault
   - `smart_list_credentials(filter?)` — list key credential (no plaintext)
   - `smart_list_sessions()` — list semua tab aktif dengan label + position +
     screenshot (untuk user monitoring)
   - `smart_close_browser()` — cleanup
2. **License server (server-side)** — FastAPI minimal:
   - `POST /license/check` — validasi user punya subscription aktif
   - `POST /tab/increment` — increment per-tab counter, reject kalau quota habis
3. **Credential vault (local)** — encrypted storage pakai libsecret/Secret Service
4. **CLI distribution** — Click-based CLI `mcp-env-browser serve` (start MCP
   stdio + monitoring HTTP) + `mcp-env-browser init` (first-time setup)
5. **Web monitoring companion** — FastAPI di `localhost:9876` serve static
   HTML grid dengan screenshot tiap session (polling 2 detik, click-to-focus)
6. **End-to-end test** dengan Hermes Agent (local), use case: scrape akun TikTok

---

## 4. Strategi: A. Local-First + License-Server-Only

Matrix scoring (5 dimensi, 1-5, dari brainstorm):

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Strategi A: Local-first + license server only                                │
├──────────────────────────────────────────────────────────────────────────────┤
│  Client = full source + Playwright + vault + MCP stdio                        │
│  Server = license DB + per-tab counter saja                                  │
│  Effort: 5  Risk: 5  Reuse: 4  KISS: 5  Match K5-K7: 3                       │
│  Total: 22/25 (juara dibanding 3 alternatif)                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Yang Anda dapatkan:**
- Berjalan cepat — server cuma license DB + counter, client full Python lokal
- Per-tab enforcement real-time — tiap `browser.new_page()` hit server
- Reuse cua-driver + libsecret + Playwright (infra sudah ada di sistem Anda)
- Migrasi ke Strategi D nanti mudah — credential vault logic reusable

**Yang Anda korbankan (disadari):**
- Source code visible ke developer (kalau distribusi binary ke non-developer,
  pakai PyInstaller/Nuitka; tetap reversible kalau target determined)
- Anti-piracy = bisnis model (license gate), bukan technical lock

**Path migrasi** (lihat `roadmap_migration.md`):
- Phase 1 (sekarang): Strategi A
- Phase 2: Strategi D — credential vault pindah ke server (master key server-side)
- Phase 3: Multi-tenant + per-target rate limit

---

## 5. Scope — File yang Disentuh (Phase 1)

| Action | Path | Tujuan | Breaking Risk |
|---|---|---|---|
| NEW | `pyproject.toml` | Poetry/PDM project config + deps | low |
| NEW | `src/mcp_env_browser/__init__.py` | Package entry | low |
| NEW | `src/mcp_env_browser/mcp_server.py` | MCP stdio server, expose tools | low |
| NEW | `src/mcp_env_browser/cli.py` | Click CLI (`serve`, `init`) | low |
| NEW | `src/mcp_env_browser/monitor.py` | FastAPI minimal untuk web monitoring (`localhost:9876`) | low |
| NEW | `src/mcp_env_browser/monitor.html` | Static HTML + vanilla JS untuk session grid | low |
| NEW | `src/mcp_env_browser/vault/` | Credential vault (libsecret adapter + KDF) | low |
| NEW | `src/mcp_env_browser/browser/` | Playwright wrapper (`smart_connect_browser`) | low |
| NEW | `src/mcp_env_browser/license/` | License client (HTTP ke server) | low |
| NEW | `src/license_server/server.py` | FastAPI server minimal | low |
| NEW | `src/license_server/db.py` | SQLite + tables (users, subscriptions, tab_counter) | low |
| NEW | `src/license_server/api/` | Routes: `/license/check`, `/tab/increment` | low |
| NEW | `install.sh` | Idempotent installer | low |
| NEW | `tests/` | pytest suite | low |
| NEW | `.env.example` | Config template | low |
| MODIFY | `README.md` | Tambah quick start | low |
| NEW | `LICENSE` | MIT | low |

---

## 6. Desain Implementasi

### 6.1 Arsitektur Sederhana

```
┌─────────────────────────────────────────────────────────────────────┐
│ Agent (Hermes/OpenAI/Claude Code)                                    │
│   │                                                                    │
│   │ MCP stdio                                                         │
│   ▼                                                                    │
│ ┌──────────────────────────────────────────┐                          │
│ │ mcp-env-browser (LOCAL — binary/source)  │                          │
│ │ ├── MCP server (stdio)                   │                          │
│ │ ├── Credential vault (libsecret)         │                          │
│ │ ├── Browser executor (Playwright)        │                          │
│ │ └── License client (HTTP) ──────────┐    │                          │
│ └──────────────────────────────────────┼────┘                          │
│                                        │ HTTPS                          │
│                                        ▼                                │
│ ┌──────────────────────────────────────────┐                          │
│ │ license-server (REMOTE — kode utama)     │                          │
│ │ ├── FastAPI                              │                          │
│ │ ├── SQLite (users, subscriptions,        │                          │
│ │ │   tab_counter)                         │                          │
│ │ └── Auth: API key per user               │                          │
│ └──────────────────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Credential Vault

- **Storage backend**: `secretstorage` (libsecret) di Linux, extensible ke
  Windows (Credential Manager) dan macOS (Keychain) di Phase 2/3
- **Schema per credential**:
  ```json
  {
    "key": "tiktok_user_alice",
    "type": "username_password",
    "username": "alice@example.com",
    "password_encrypted": "libsecret://...",
    "created_at": "2026-08-16T...",
    "updated_at": "2026-08-16T..."
  }
  ```
- **Supported types** (Phase 1):
  - `username_password` (web login)
  - `api_key` (env-var style)
  - `oauth_token` (with refresh_token field)
  - `ssh_key` (path + passphrase)
- **Master key**: TIDAK dipakai untuk encrypt-at-rest (libsecret sudah handle)
  — Phase 2 akan pakai master key untuk additional layer

### 6.3 Per-Tab Counter

- Setiap `browser.new_page()` di `smart_connect_browser()`:
  1. Check license via `POST /license/check` → kalau invalid/expired, raise error
  2. Increment counter via `POST /tab/increment` → kalau quota habis, raise error
  3. Baru buka tab
- **HTTP timeout**: 2 detik (kalau server mati, fail-fast — agent tahu)

### 6.4 MCP Tools (Fase 1)

**Goal revisi (2026-08-16)**: Agent = **user replacement di browser**. Bisa
klik-klik, type, scroll, navigate — seperti manusia, untuk ambil alih task
yang biasanya user lakukan manual. Spec tools di bawah adalah **minimum
yang memenuhi goal ini** — bukan inventaris lengkap.

| Tool | Args | Returns |
|---|---|---|
| `smart_list_credentials` | `filter?: str` | `[{key, type, summary}]` (no plaintext) |
| `smart_get_credential_meta` | `key: str` | `{key, type, username, created_at}` (no password) |
| `smart_set_credential` | `key, type, value: dict` | `{ok: true, key}` |
| `smart_delete_credential` | `key: str` | `{ok: true}` |
| `smart_connect_browser` | `target: str, credential_key: str, label?: str` | `{session_id, label, page_handle, position}` (Playwright page; label untuk multi-tab clarity) |
| `smart_list_sessions` | `include_screenshot?: bool = false` | `[{session_id, label, position, url, status, age_seconds, last_screenshot_b64?}]` (all open tabs left-to-right) |
| `smart_close_browser` | `session_id?: str` | `{ok: true}` |
| `smart_browser_action` | `session_id, action: str, ...` | action-specific result (navigate, click, type, scroll, drag, hover, screenshot, wait, evaluate) |
| `smart_browser_console_log` | `session_id, type?: str` | `[log entries]` (Console API via CDP) |
| `smart_browser_network_log` | `session_id, filter?: str` | `[network entries]` (Network API via CDP) |
| `smart_browser_inspect` | `session_id, selector: str` | `{tag, attrs, computed_style, children}` (DOM API via CDP) |
| `smart_session_pause` | `session_id, reason: str` | `{paused: true, label, position, screenshot_base64, url, hint}` (user intervene untuk CAPTCHA/2FA) |
| `smart_session_resume` | `session_id` | `{resumed: true, page_handle, state}` (lanjut otomatis setelah user solve) |

**Session identity & multi-tab clarity** (untuk user-replacement goal):

- **`label`** — optional human-readable identifier per session. Agent specify
  saat panggil `smart_connect_browser(target, credential_key, label='TikTok Login')`.
  Default = auto-generated dari domain (mis: `'tiktok.com'` → `'TikTok'`).
  Contoh penggunaan:
  ```python
  # Agent buka 3 tab sekaligus, label beda biar jelas
  await call_tool("smart_connect_browser", {
      "target": "https://www.tiktok.com/login",
      "credential_key": "tiktok_main",
      "label": "TikTok Main - Login"
  })
  # → session_id=abc, label="TikTok Main - Login", position=0

  await call_tool("smart_connect_browser", {
      "target": "https://console.cloud.google.com/billing",
      "credential_key": "gcp_billing",
      "label": "GCP Billing Dashboard"
  })
  # → session_id=def, label="GCP Billing Dashboard", position=1
  ```
- **`position`** — left-to-right tab ordering (0 = paling kiri). Sync dengan
  visual tab order di browser. Agent baca via `smart_list_sessions`.
- **`smart_list_sessions`** — list semua session aktif dengan label + position.
  Optional `include_screenshot=true` untuk embed thumbnail (max 1 per session
  untuk hemat bandwidth). Return:
  ```json
  [
    {"session_id": "abc", "label": "TikTok Main - Login", "position": 0,
     "url": "https://www.tiktok.com/login", "status": "active", "age_seconds": 45},
    {"session_id": "def", "label": "GCP Billing Dashboard", "position": 1,
     "url": "https://console.cloud.google.com/billing", "status": "paused",
     "age_seconds": 120, "last_screenshot_b64": "iVBORw0K..."}
  ]
  ```

**Bedah tambahan tools (untuk user-replacement goal)**:

- **`smart_session_pause`** — Saat agent detect CAPTCHA/2FA/visual challenge
  yang tidak bisa di-automate, agent pause session + return screenshot.
  User solve manual di browser yang sedang aktif (local user, karena
  browser di local — K2). Session tetap terbuka, state preserved.
  `reason` = `"captcha" | "2fa" | "manual_review" | "other"`. Returns
  `screenshot_base64` untuk agent kasih ke user via response text, `label`
  dan `position` untuk multi-tab clarity, dan `hint` yang menyebut tab
  spesifik (contoh: `"please solve the CAPTCHA in tab 'TikTok Login'
  (position 2)"`).
- **`smart_session_resume`** — Setelah user solve, agent panggil ini.
  Returns fresh `page_handle` + state apakah session masih valid (kalau
  CAPTCHA expire = return error). Tidak ada timeout — agent boleh poll
  lama.

**Action list di `smart_browser_action`** (eksplisit, sesuai goal user-replacement):

| Action | Args | Notes |
|---|---|---|
| `navigate` | `url` | goto page |
| `click` | `selector` | element click (wait for visible first) |
| `type` | `selector, text, delay_ms?` | realistic typing (default 50ms/char, random jitter) |
| `scroll` | `direction, amount` | up/down/left/right |
| `drag` | `from_selector, to_selector` | drag-drop interaction |
| `hover` | `selector` | mouse hover (trigger tooltip/dropdown) |
| `screenshot` | `full_page?, clip?` | return base64 PNG |
| `wait_for` | `selector?, timeout_ms?` | wait for selector or timeout |
| `wait_for_navigation` | `timeout_ms?` | wait until URL changes |
| `evaluate` | `js_code` | execute JS in page context (sandboxed) |
| `select_option` | `selector, value` | for `<select>` dropdown |
| `press_key` | `key` | keyboard key (Enter, Tab, Escape, arrow) |

### 6.4.1 MCP Prompts (Fase 1)

MCP `Prompt` primitive adalah prompt template dengan `name + description + arguments[]`
yang return `PromptMessage[]` siap di-inject ke LLM context. Bedanya dengan Tool:
Tool return data, Prompt return **instructional messages** untuk guide LLM ambil
action sequence.

**3 Prompt** untuk Phase 1 — dipilih dari 4 goal berdasarkan analisis value (lihat
`refactor/95_anti_overengineering_guard.md` §Examples). 1 Prompt lain
(first_run_setup, scrape_*_per_service) **di-defer ke Phase 2** karena
value-nya low untuk goal spesifik (overhead > value).

#### Prompt 1: `oauth_confirmation_flow`

**Use case**: Saat LLM dapat error `oauth_required` dari `smart_connect_browser`
atau `smart_browser_action`, LLM butuh pattern terbaik untuk handle re-auth
interaktif dengan user.

**Schema**:
```json
{
  "name": "oauth_confirmation_flow",
  "description": "Pattern untuk handle OAuth re-authentication flow ketika credential OAuth expired atau tidak ada. Use ini saat dapat error 'oauth_required' dari tool lain.",
  "arguments": [
    {"name": "service", "required": true, "description": "Nama service (gcp/tiktok/coreta x/github/dll)"},
    {"name": "scopes", "required": false, "description": "OAuth scopes yang dibutuhkan (comma-separated)"}
  ]
}
```

**Returns (PromptMessage[])** — instructional wrapper:
```
[User] OAuth re-authentication flow untuk {service}

[Assistant] Pattern berikut untuk handle OAuth confirmation:

1. Detect: cek response tool sebelumnya untuk error code "oauth_required"
2. Open auth URL: panggil smart_connect_browser dengan auth_url={provider_auth_url}
   (URL construction hardcoded per service, lihat knowledge.md §OAuth URLs)
3. Inform user: kasih instruksi di response text ke user:
   "Silakan login manual di browser yang terbuka. Sistem akan otomatis detect selesai."
4. Poll vault: panggil smart_list_credentials tiap 5 detik, cek apakah
   credential_key={service}_oauth ter-update
5. Retry: setelah token baru tersedia, retry original request dengan
   credential_key yang baru
6. Timeout: kalau 60 detik belum selesai, kasih instruksi alternatif
   (paste token manual via smart_set_credential)

JANGAN auto-input password user. JANGAN skip langkah user confirmation.
OAuth melibatkan privasi user — selalu minta eksplisit confirmation.
```

**Implementation**: `app.list_prompts()` + `app.get_prompt()` di MCP server.
Return messages format sesuai `PromptMessage` schema (verified dari
`modelcontextprotocol/specification/schema/2025-11-25/schema.json` `$defs/PromptMessage`).

---

#### Prompt 2: `browser_debug_workflow`

**Use case**: Saat LLM bingung kenapa UI flow gagal (button tidak klik,
data tidak muncul, layout rusak), Prompt kasih pattern investigation pakai
DevTools tools.

**Schema**:
```json
{
  "name": "browser_debug_workflow",
  "description": "Pattern investigasi UI flow failure pakai DevTools (Console/Network/DOM). Use ini saat smart_browser_action return error atau hasil tidak sesuai expectation.",
  "arguments": [
    {"name": "symptom", "required": true, "description": "Apa yang diamati (mis: 'tombol klik tidak trigger submit', 'data tidak muncul di tabel', 'page redirect ke unexpected URL')"}
  ]
}
```

**Returns (PromptMessage[])** — instructional wrapper:
```
[User] Browser debug workflow untuk symptom: {symptom}

[Assistant] Pattern investigation 4 langkah:

1. Console: panggil smart_browser_console_log(session_id, level="error")
   → cek apakah ada JS error atau 4xx/5xx response logged
   
2. Network: panggil smart_browser_network_log(session_id, filter=".{service}.com")
   → cek request terakhir: status code, response time, headers
   → khusus cari: 401 (auth expired), 403 (forbidden), 429 (rate limit), 5xx

3. DOM: panggil smart_browser_inspect(session_id, selector="<suspect_element>")
   → cek: ada element? computed_style visible? attribute benar?
   → kalau element tidak ada, inspect parent container

4. Correlate: gabungkan findings dari 3 langkah di atas
   - Console error + Network 4xx = biasanya auth atau validation issue
   - Console clean + Network 200 + DOM wrong = UI state bug
   - Console error + Network 200 = biasanya JS exception tidak terkait network

Setelah root cause teridentifikasi, retry action dengan parameter yang dikoreksi,
atau escalate ke user kalau butuh input manual.
```

**Implementation**: sama dengan Prompt 1, di MCP server `list_prompts()` +
`get_prompt()`.

#### Prompt 3: `human_intervention_workflow` (User-Replacement Pattern)

**Use case**: Saat agent detect visual challenge (CAPTCHA, 2FA, photo
verification) atau situasi yang butuh user lihat + putuskan (mis: konfirmasi
purchase, klik tombol setuju ToS), Prompt kasih pattern pause → user solve
→ resume. Ini **goal utama user-replacement** (agent = user pengganti di
browser, bukan 100% autonomous — user intervene saat diperlukan).

**Schema**:
```json
{
  "name": "human_intervention_workflow",
  "description": "Pattern pause session dan minta user intervene saat visual challenge (CAPTCHA/2FA) atau decision penting (konfirmasi purchase, accept ToS). Browser tetap terbuka untuk user, agent pause sampai user solve.",
  "arguments": [
    {"name": "challenge_type", "required": true, "description": "captcha | 2fa | manual_review | purchase_confirmation | tos_accept | other"},
    {"name": "context", "required": false, "description": "Tambah context apa yang sedang dilakukan agent (mis: 'submitting tax form, halaman konfirmasi muncul')"}
  ]
}
```

**Returns (PromptMessage[])** — instructional wrapper:
```
[User] Human intervention workflow untuk {challenge_type}{context}

[Assistant] Pattern pause/resume session:

1. Detect: cek response smart_browser_inspect atau smart_browser_action
   untuk sinyal challenge:
   - CAPTCHA: element dengan class mengandung 'captcha', 'hcaptcha', 'recaptcha'
   - 2FA: input field untuk OTP code, atau tombol 'verify device'
   - Purchase confirmation: tombol 'confirm purchase' / 'pay now' / 'place order'
   - ToS: tombol 'I agree' / 'accept terms'

2. Pause: panggil smart_session_pause(session_id, reason="{challenge_type}")
   → server returns screenshot_base64 + label + position + hint
   → PENTING: hint menyebut label spesifik tab supaya user tidak miss komunikasi
     Contoh hint: "Please solve the CAPTCHA in tab 'TikTok Login' (position 2)."
   → IMPORTANT: jangan panggil smart_close_browser — session harus tetap hidup

3. Inform user: kasih response ke user dengan:
   - Embed screenshot base64 sebagai image (kalau UI support)
   - Sampaikan hint dari server ("silakan solve CAPTCHA di browser yang terbuka")
   - Minta konfirmasi: "sudah selesai? bilang 'lanjut'"

4. Tunggu user confirmation: agent masuk ke loop tunggu response dari user.
   Jangan polling panggil smart_session_resume sebelum user confirm.

5. Resume: setelah user bilang 'lanjut' / 'selesai', panggil
   smart_session_resume(session_id) → server verify session masih valid
   + return fresh page_handle + state.

6. Verify: cek apakah halaman sudah berubah (mis: dari CAPTCHA ke dashboard).
   Kalau session expire / CAPTCHA timeout, retry dari step 2.

PENTING: JANGAN auto-input CAPTCHA / OTP dari agent. Itu privasi user.
Kalau user tidak respond dalam 5 menit, kasih instruksi bahwa session
masih terbuka (user bisa lanjut kapan saja).
```

**Implementation**: sama dengan Prompt 1, di MCP server `list_prompts()` +
`get_prompt()`.

### 6.5 License Server Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/license/check` | `{api_key}` | `{valid: bool, plan, tabs_used, tabs_quota, expires_at}` |
| `POST` | `/tab/increment` | `{api_key, amount?: int}` | `{ok: bool, tabs_used, tabs_quota_remaining}` |
| `POST` | `/license/register` | `{email, plan}` | `{api_key, plan, expires_at}` (admin only Phase 1) |
| `GET`  | `/health` | — | `{status: "ok"}` |

**Auth**: simple API key per user (random 32-char hex). Phase 2 akan pakai
JWT dengan subscription tier.

---

### 6.6 Web Monitoring (Companion UI)

> **Purpose**: User bisa lihat real-time apa yang sedang agent lakukan di
> browser — seperti billing warnet yang menampilkan screen tiap client. Plus
> click-to-act: user klik session card untuk langsung intervene.

**Trigger use case** (dari user requirement 2026-08-16):
> "agent perlu klik recaptcha dan meminta user untuk melakukannya, tetapi
> tab yang terbuka lebih dari satu — instruksinya harus jelas supaya antara
> user dan agent tidak miss komunikasi"

**Design constraint**: Minimum untuk goal ini, tanpa over-engineering.

#### 6.6.1 Arsitektur

```
mcp-env-browser (CLI serve)
  ├── MCP stdio (untuk agent)
  └── HTTP server di localhost:9876 (untuk monitoring UI)
       ├── GET /         → static HTML (single page, polling-based) — Phase 1
       ├── GET /api/sessions → list sessions (label, position, status, screenshot)
       └── POST /api/sessions/{id}/focus → bring browser window to front
```

**Bukan** SSE/WebSocket — polling HTTP tiap 2 detik cukup untuk Phase 1
(monitor visual, bukan real-time gaming).

**Stack decision (verified 2026-08-16)**:

| Phase | Stack | Alasan |
|---|---|---|
| **Phase 1 (sekarang)** | vanilla JS + plain HTML + inline CSS | 1 page polling, no framework lock-in, 0 KB bundle, no build step. KISS principle. |
| **Phase 3 (dashboard)** | Vite + Svelte + Routify + Tailwind | Multi-page (overview/usage/billing/subscription/settings), auth (JWT), state kompleks. Stack besar = worth it. |

**Mengapa tidak pakai Vite+Svelte+Routify+Tailwind dari awal**:
- Phase 3 dashboard berbeda total dengan Phase 1 monitoring (auth, multi-page, complex state)
- 1 page UI tidak butuh framework = anti-over-engineering
- Refactor vanilla → Svelte saat Phase 3 mulai = effort ~2-3 jam (monitoring logic sederhana)
- Build step premature untuk 1 file HTML

**Mengapa tidak 2 app terpisah** (monitoring + dashboard):
- Owner requirement: "user tidak ribet" → 1 unified surface lebih simple
- 1 URL (`localhost:9876`) untuk monitoring + dashboard di Phase 3
- Data lokal SQLite (privacy, MIT spirit, K5 anti-piracy)

**Mengapa tidak desktop app (Tauri/Electron)**:
- Extra packaging complexity (.deb/.AppImage signing)
- Install friction per device
- Browser sudah built-in OS user, no need for native wrapper

**Mengapa tidak remote web app** (app.mcp-env-browser.com):
- Data di server = privacy concern (bertentangan dengan K5 anti-piracy spirit)
- Tidak offline-ready (kalau server mati, monitoring mati)
- Owner concern "data local" lebih kuat dari multi-device access untuk Phase 1

#### 6.6.2 UI Layout

Grid layout, 1 card per session, ordered left-to-right by position:

```
┌─────────────────────────────────────────────────────────┐
│  mcp-env-browser Monitor       [Refresh every 2s]        │
├─────────────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                    │
│  │  Tab 0  │ │  Tab 1  │ │  Tab 2  │                    │
│  │ TikTok  │ │  GCP    │ │ Coretax │                    │
│  │ Login   │ │ Billing │ │  DJP    │                    │
│  │         │ │         │ │  [PAUSE]│ ← status badge    │
│  │ [image] │ │ [image] │ │ [image] │                    │
│  │ ACTIVE  │ │ ACTIVE  │ │ PAUSED  │                    │
│  │ 45s old │ │ 120s old│ │ 30s old │                    │
│  │ [Focus] │ │ [Focus] │ │ [Focus] │ ← click to act    │
│  └─────────┘ └─────────┘ └─────────┘                    │
└─────────────────────────────────────────────────────────┘
```

#### 6.6.3 Session Card Interaction

- **Hover**: highlight border + tooltip dengan URL
- **Click**: bring browser window to front + focus the tab (Phase 1 simple;
  Phase 2 bisa juga trigger pause/resume button)
- **Status badge**:
  - `ACTIVE` (hijau) — session running normal
  - `PAUSED` (kuning) — waiting user intervention
  - `CAPTCHA` (merah) — explicit CAPTCHA challenge detected
  - `ERROR` (abu-abu) — session invalid/closed

#### 6.6.4 Implementation Notes

**File**: `src/mcp_env_browser/monitor.py` (FastAPI minimal, serve HTML+API)

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx

app = FastAPI()

@app.get("/api/sessions")
async def list_sessions():
    # Delegate ke browser executor (sama dengan smart_list_sessions MCP tool)
    return browser_executor.list_sessions(include_screenshot=True)

@app.post("/api/sessions/{session_id}/focus")
async def focus_session(session_id: str):
    # Bring browser window + tab ke front
    browser_executor.focus_session(session_id)
    return {"ok": True}

@app.get("/")
async def index():
    return HTMLResponse(open("monitor.html").read())
```

**HTML file**: `src/mcp_env_browser/monitor.html` (vanilla JS, no framework):

```html
<!DOCTYPE html>
<html>
<head><title>mcp-env-browser Monitor</title></head>
<body>
<h1>mcp-env-browser Monitor</h1>
<div id="sessions"></div>
<script>
async function refresh() {
  const r = await fetch('/api/sessions');
  const sessions = await r.json();
  document.getElementById('sessions').innerHTML = sessions.map(s => `
    <div class="card" data-id="${s.session_id}" onclick="focusSession('${s.session_id}')">
      <div class="label">${s.label} (Tab ${s.position})</div>
      <img src="data:image/png;base64,${s.last_screenshot_b64}" />
      <div class="status status-${s.status}">${s.status}</div>
    </div>
  `).join('');
}
async function focusSession(id) {
  await fetch(`/api/sessions/${id}/focus`, {method: 'POST'});
}
setInterval(refresh, 2000);
refresh();
</script>
<style>
  .card { display: inline-block; border: 1px solid #ccc; margin: 8px; padding: 8px; cursor: pointer; }
  .card:hover { border-color: #007bff; }
  .status-active { color: green; }
  .status-paused { color: orange; }
  .status-captcha { color: red; }
  img { max-width: 300px; }
</style>
</body>
</html>
```

#### 6.6.5 Distribusi & Security

- **Local only**: HTTP server bind ke `127.0.0.1:9876`, TIDAK exposed ke network
- **No auth**: localhost only, OS-level access control cukup. Phase 2 tambah
  Bearer token kalau perlu expose ke LAN
- **Auto-start**: `mcp-env-browser serve` start both MCP stdio + monitoring
  HTTP. CLI flag `--no-monitor` untuk opt-out
- **Screenshot size**: 800x600 max, JPEG quality 60 — hemat bandwidth

#### 6.6.6 Phase 2 Roadmap (DEFER)

- SSE streaming untuk real-time (instead of polling 2s)
- Multiple browser window support (kalau Playwright launch multi-window)
- Remote access via tunnel (cloudflared/ngrok) untuk lihat dari device lain
- Click-to-pause / click-to-resume button di UI

---

## 7. Quality Gates (Phase 1)

- [ ] **Functional**: semua MCP tools listed di §6.4 berfungsi end-to-end via
  Hermes Agent
- [ ] **Per-tab counter**: simulasi 100 tabs, counter akurat
- [ ] **License gate**: API key invalid → return error, tidak buka tab
- [ ] **Vault roundtrip**: set credential → restart MCP → get credential masih sama
- [ ] **Web monitoring**: `mcp-env-browser serve` buka `http://localhost:9876`,
  tampilkan session cards dengan screenshot real-time
- [ ] **Session identity**: 3 tab berbeda, masing-masing label berbeda, user
  tidak miss komunikasi saat pause/resume
- [ ] **Click-to-act**: klik session card di monitoring → browser window
  fokus ke tab yang dimaksud
- [ ] **Build**: `python -m build` sukses, wheel ter-generate
- [ ] **Tests**: pytest ≥80% coverage di core modules
- [ ] **Docs**: README quick start + install.sh tested fresh di popOS

---

## 8. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Server mati = agent total stop | High | Tambah offline mode (cache license check 5 menit) di Phase 2 |
| User bypass license (intercept HTTP) | Medium | Counter sync batch + alert anomali (Phase 2) |
| libsecret tidak ada di Windows/Mac | Low Phase 1 | Extensible adapter pattern, Phase 2/3 implementasi |
| MCP stdio flaky | Medium | Reconnect logic + clear error message |
| Credential bocor via agent log | High | Vault tool **never** return plaintext ke agent context, hanya dipakai internal |

---

## 9. Acceptance Criteria

Phase 1 dianggap DONE kalau:
1. ✅ `mcp-env-browser init` sukses di popOS user (Anda)
2. ✅ `mcp-env-browser serve` bisa di-connect dari Hermes Agent via `.mcp.json`
3. ✅ End-to-end: agent scrape akun TikTok via `smart_connect_browser` → data
   JSON kembali ke agent
4. ✅ Per-tab counter akurat (cek di server DB)
5. ✅ License gate: API key invalid → error message jelas, tidak crash
6. ✅ Install script idempotent (run 2x = same result)
7. ✅ Tests pass
8. ✅ Spec ini di-archive dengan quality_gates status ter-update

---

## 10. Cross-Reference

- `state.json` — SSOT fase + quality gates (machine-readable)
- `knowledge.md` — reuse catatan infra (cua-driver, libsecret, Playwright)
- `roadmap_migration.md` — Strategi A → D → fase 3
- `refactor/00_overview.md` — Quick split matrix + scope contract
- `refactor/10_mcp_server.md` — Detail MCP tool spec
- `refactor/20_license_server.md` — Detail server endpoint spec
- `refactor/30_client_arch.md` — Local-first client structure
- `refactor/40_distribution.md` — PyInstaller binary + install script
- `refactor/90_decisions_log.md` — CAPTURE K1-K7 (jangan dihapus)