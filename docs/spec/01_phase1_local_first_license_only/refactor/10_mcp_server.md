# 10 — MCP Server Spec (Local Client)

> Detail teknis untuk `src/mcp_env_browser/mcp_server.py` + CLI entry point.

---

## Module Map

```
src/mcp_env_browser/
├── __init__.py            # package version, constants
├── cli.py                 # Click CLI (init, serve, version)
├── mcp_server.py          # MCP stdio server — exposes 13 tools + 3 prompts
├── vault/                 # credential storage (see 30_client_arch.md)
├── browser/               # Playwright wrapper (see 30_client_arch.md)
└── license/               # license client (HTTP ke server)
    ├── __init__.py
    └── client.py
```

---

## CLI Commands (Click)

### `mcp-env-browser init`

First-time setup. Tasks:
1. Check `~/.config/mcp-env-browser/` exists, create if not
2. Generate atau import API key (prompt user, simpan ke `config.json`)
3. Validate connectivity ke license server (`POST /health`)
4. Initialize vault backend (test secretstorage write/read)
5. Print summary + next steps

**Idempotent**: kalau sudah jalan, skip steps yang sudah done.

### `mcp-env-browser serve`

Start MCP stdio server. Tasks:
1. Load `config.json` (API key, server URL)
2. Init vault backend + license client + browser executor
3. Start `mcp_server.py` async loop

**No flags** — semua config via `config.json` atau env var.

### `mcp-env-browser version`

Print version (`__version__` dari `__init__.py`).

### `mcp-env-browser config`

Show/edit config. Subcommands:
- `config show` — print current config (masked API key)
- `config set-server-url <url>`
- `config set-api-key <key>`
- `config path` — print config file path

---

## MCP Tools — Detail Spec

### 1. `smart_list_credentials(filter?: str) -> [{key, type, summary}]`

**Purpose**: List semua credential key yang tersimpan. **No plaintext**.

**Args**:
- `filter` (optional): substring match terhadap key/type

**Returns**:
```json
[
  {"key": "tiktok_user_alice", "type": "username_password", "summary": "alice@example.com"},
  {"key": "gcp_sa_billing", "type": "api_key", "summary": "***last4:AB12"},
  {"key": "github_oauth_yaden", "type": "oauth_token", "summary": "***exp:2026-12-01"}
]
```

**Implementation**:
```python
@app.call_tool()
async def call_tool(name: str, args: dict):
    if name == "smart_list_credentials":
        keys = vault.list_keys(args.get("filter"))
        return [TextContent(type="text", text=json.dumps(keys))]
```

---

### 2. `smart_get_credential_meta(key: str) -> {key, type, username, created_at}`

**Purpose**: Get metadata (no password).

**Returns**:
```json
{
  "key": "tiktok_user_alice",
  "type": "username_password",
  "username": "alice@example.com",
  "created_at": "2026-08-16T..."
}
```

**Security**: tidak pernah return field `password`/`value`/`token`.

---

### 3. `smart_set_credential(key: str, type: str, value: dict) -> {ok: true}`

**Purpose**: Save credential baru atau overwrite.

**Args**:
```json
{
  "key": "tiktok_user_alice",
  "type": "username_password",
  "value": {
    "username": "alice@example.com",
    "password": "hunter2"
  }
}
```

**Supported types Phase 1**:
- `username_password` — value: `{username, password}`
- `api_key` — value: `{key}`
- `oauth_token` — value: `{access_token, refresh_token?, expires_at?}`
- `ssh_key` — value: `{path, passphrase?}`

**Implementation**:
```python
# vault.set() — auto-encrypt via libsecret
vault.set(key, value, attributes={"type": type, "app": "mcp-env-browser"})
```

---

### 4. `smart_delete_credential(key: str) -> {ok: true}`

**Purpose**: Hapus credential. Confirmation via separate `smart_confirm`
tool kalau dipanggil dari agent (Phase 2).

---

### 5. `smart_connect_browser(target: str, credential_key: str, label?: str) -> {session_id, label, page_handle, position}`

**Purpose**: Buka browser, login pakai credential dari vault. **`label`**
optional untuk multi-tab clarity — agent bisa specify nama manusia-baca
(contoh: `"TikTok Login"`).

**Args**:
- `target`: domain/url (e.g., `"https://www.tiktok.com/@alice"`)
- `credential_key`: key di vault (e.g., `"tiktok_user_alice"`)
- `label` (optional): human-readable identifier. Default = auto-generated dari
  domain. Contoh: `target="https://www.tiktok.com/login"` → label default
  `"TikTok"`. Agent boleh specify sendiri: `label="TikTok Main - Login"`.

**Returns**:
```json
{
  "session_id": "uuid",
  "label": "TikTok Main - Login",
  "page_handle": "page_ref_123",
  "position": 0,
  "browser_active": true
}
```

**Side effects**:
1. License check (`POST /license/check`) → kalau invalid, raise
2. Counter increment (`POST /tab/increment`) → kalau quota habis, raise
3. Launch Playwright (kalau belum)
4. Auto-login pakai `credential_key` (workflow hardcoded per target Phase 1)
5. Append session ke list, assign position left-to-right

**Security**: plaintext password **tidak pernah** return ke agent. Agent
cuma dapat `page_handle` untuk interaksi lanjutan.

**Counter increment WAJIB** sebelum `browser.new_page()`. Tidak ada bypass.

**Label generation fallback** (kalau agent tidak specify):
```python
def _default_label(target: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(target)
    domain = parsed.netloc.replace("www.", "")
    # Capitalize first letter + remove TLD
    parts = domain.split(".")
    if len(parts) >= 2:
        return parts[0].capitalize()  # "tiktok.com" → "Tiktok"
    return domain.capitalize()
```

---

### 6. `smart_list_sessions(include_screenshot?: bool = false) -> [{session_id, label, position, url, status, age_seconds, last_screenshot_b64?}]`

**Purpose**: List semua session aktif, ordered left-to-right by position.
Untuk agent tahu tab mana yang sedang jalan, dan untuk web monitoring UI.

**Args**:
- `include_screenshot` (optional, default false): kalau true, include
  `last_screenshot_b64` per session. Default false hemat bandwidth untuk
  context agent. Web monitoring pakai true.

**Returns**:
```json
[
  {
    "session_id": "abc",
    "label": "TikTok Main - Login",
    "position": 0,
    "url": "https://www.tiktok.com/login",
    "status": "active",
    "age_seconds": 45,
    "last_screenshot_b64": null  // null kalau include_screenshot=false
  },
  {
    "session_id": "def",
    "label": "GCP Billing Dashboard",
    "position": 1,
    "url": "https://console.cloud.google.com/billing",
    "status": "paused",
    "age_seconds": 120,
    "last_screenshot_b64": null
  }
]
```

**Implementation**:
```python
@app.call_tool()
async def call_tool(name, args):
    if name == "smart_list_sessions":
        include_shot = args.get("include_screenshot", False)
        sessions = browser_executor.list_sessions(include_screenshot=include_shot)
        return [TextContent(type="text", text=json.dumps(sessions))]
```

**Status values**:
- `active` — session running normal
- `paused` — paused via `smart_session_pause`, waiting user
- `captcha` — explicit CAPTCHA challenge detected (heuristic)
- `error` — session invalid/closed

---

### 7. `smart_close_browser(session_id?: str) -> {ok: true}`

**Purpose**: Cleanup. Kalau `session_id` None, close all sessions.

---

### 7. `smart_browser_action(session_id: str, action: str, ...) -> result`

**Purpose**: Action di browser yang sedang aktif. **Memenuhi goal
user-replacement**: agent bisa klik-klik, type, scroll, drag, hover — seperti
manusia.

**Supported actions Phase 1** (12 total, semua sesuai user-replacement):

| Action | Args | Notes |
|---|---|---|
| `navigate` | `url: str` | goto page |
| `click` | `selector: str` | element click (wait for visible first) |
| `type` | `selector: str, text: str, delay_ms?: int = 50` | realistic typing dengan random jitter |
| `scroll` | `direction: str, amount: int` | `up | down | left | right` |
| `drag` | `from_selector: str, to_selector: str` | drag-drop interaction |
| `hover` | `selector: str` | mouse hover (trigger tooltip/dropdown) |
| `screenshot` | `full_page?: bool = false, clip?: dict` | return base64 PNG |
| `wait_for_selector` | `selector: str, timeout_ms?: int = 5000` | wait for selector visible |
| `wait_for_navigation` | `timeout_ms?: int = 10000` | wait until URL changes |
| `evaluate` | `js_code: str` | execute JS in page context (sandboxed) |
| `select_option` | `selector: str, value: str` | for `<select>` dropdown |
| `press_key` | `key: str` | keyboard key (Enter, Tab, Escape, ArrowUp, etc.) |

**Returns**: action-specific JSON.

**Implementation**:
```python
def action(self, session_id: str, action: str, **kwargs) -> dict:
    page = self._sessions[session_id]["page"]
    handler = self._action_handlers.get(action)
    if not handler:
        raise ValueError(f"unknown action: {action}")

    # Realistic typing: random jitter antara chars
    if action == "type":
        delay = kwargs.get("delay_ms", 50)
        for char in kwargs["text"]:
            page.keyboard.type(char, delay=random.randint(delay - 20, delay + 20))

    return handler(page, **kwargs)

_action_handlers = {
    "navigate": lambda p, **kw: p.goto(kw["url"]),
    "click": lambda p, **kw: p.click(kw["selector"], timeout=5000),
    "type": lambda p, **kw: ... ,  # handled specially above
    "scroll": lambda p, **kw: p.mouse.wheel(0, kw["amount"]) if kw["direction"] == "down" else p.mouse.wheel(0, -kw["amount"]),
    "drag": lambda p, **kw: p.locator(kw["from_selector"]).drag_to(p.locator(kw["to_selector"])),
    "hover": lambda p, **kw: p.locator(kw["selector"]).hover(),
    "screenshot": lambda p, **kw: {"base64": base64.b64encode(p.screenshot(full_page=kw.get("full_page", False))).decode()},
    "wait_for_selector": lambda p, **kw: p.locator(kw["selector"]).wait_for(timeout=kw.get("timeout_ms", 5000)),
    "wait_for_navigation": lambda p, **kw: p.wait_for_url("**", timeout=kw.get("timeout_ms", 10000)),
    "evaluate": lambda p, **kw: p.evaluate(kw["js_code"]),
    "select_option": lambda p, **kw: p.select_option(kw["selector"], kw["value"]),
    "press_key": lambda p, **kw: p.keyboard.press(kw["key"]),
}
```

---

### 8. `smart_browser_console_log(session_id: str, type?: str) -> [log entries]`

**Purpose**: Get browser console messages via CDP `Console.messageAdded`.

**Args**:
- `type`: filter by log type (`log`, `warn`, `error`, `info`, `debug`)

**Returns**:
```json
[
  {"level": "error", "text": "Failed to load resource: 404", "url": "...", "timestamp": "..."}
]
```

**Implementation**: pakai `cdp.py` helper untuk subscribe CDP events.

---

### 9. `smart_browser_network_log(session_id: str, filter?: str) -> [network entries]`

**Purpose**: Get network requests via CDP `Network.requestWillBeSent` +
`Network.responseReceived`.

**Args**:
- `filter`: substring match URL

**Returns**:
```json
[
  {"url": "https://api.tiktok.com/...", "method": "POST", "status": 200, "duration_ms": 234}
]
```

---

### 10. `smart_browser_inspect(session_id: str, selector: str) -> DOM info`

**Purpose**: Inspect DOM element via CDP `DOM.getDocument` + `DOM.querySelector`.

**Returns**:
```json
{
  "tag": "div",
  "attrs": {"class": "username", "id": "..."},
  "computed_style": {"color": "rgb(0,0,0)", "font-size": "14px"},
  "children_count": 3,
  "outer_html_truncated": "..."
}
```

---

## Async Pattern

Semua MCP tool handler `async def`. Sync Playwright di-wrap:

```python
import asyncio
from playwright.sync_api import sync_playwright

def _sync_login(page, username, password):
    page.fill("input[name='email']", username)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")

@app.call_tool()
async def call_tool(name, args):
    if name == "smart_connect_browser":
        # ... license check + counter increment ...
        result = await asyncio.to_thread(_sync_login, page, username, password)
        return result
```

---

## Error Handling

Semua error di-return sebagai MCP error response, **tidak raise**:

```python
@app.call_tool()
async def call_tool(name, args):
    try:
        # ... logic ...
        return [TextContent(type="text", text=json.dumps({"ok": True, "data": ...}))]
    except LicenseInvalid as e:
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": "license_invalid", "message": str(e)}))]
    except QuotaExceeded as e:
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": "quota_exceeded", "message": str(e)}))]
    except VaultError as e:
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": "vault_error", "message": str(e)}))]
    except Exception as e:
        logger.exception("mcp tool failed", extra={"tool": name, "args": args})
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": "internal", "message": str(e)}))]
```

---

## Logging

- **Stdout**: JANGAN print (break MCP protocol)
- **Stderr**: pakai `logging` module, structured JSON
- **Log file**: `~/.local/share/mcp-env-browser/logs/server.log` (rotated)

---

## Testing Strategy

- **Unit**: mock vault + license client, test MCP tool return shape
- **Integration**: real MCP stdio via subprocess, verify JSON parse
- **Manual**: end-to-end Hermes Agent + scrape akun TikTok (lihat `spec.md` §9)

---

## MCP Prompts — Detail Spec

> **3 Prompt** untuk Phase 1 — dipilih dari analisis value per goal
> (lihat `spec.md` §6.4.1). Tambah Prompt baru butuh diskusi owner.

### Pattern Implementation

```python
from mcp.server import Server
from mcp.types import Prompt, PromptMessage, PromptArgument, TextContent

app = Server("mcp-env-browser")

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="oauth_confirmation_flow",
            description="Pattern untuk handle OAuth re-authentication flow...",
            arguments=[
                PromptArgument(name="service", required=True, description="..."),
                PromptArgument(name="scopes", required=False, description="..."),
            ],
        ),
        Prompt(
            name="browser_debug_workflow",
            description="Pattern investigasi UI flow failure pakai DevTools...",
            arguments=[
                PromptArgument(name="symptom", required=True, description="..."),
            ],
        ),
    ]

@app.get_prompt()
async def get_prompt(name: str, arguments: dict) -> list[PromptMessage]:
    if name == "oauth_confirmation_flow":
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"OAuth re-authentication flow untuk {arguments['service']}",
                ),
            ),
            PromptMessage(
                role="assistant",
                content=TextContent(
                    type="text",
                    text=_render_oauth_flow(arguments),
                ),
            ),
        ]
    if name == "browser_debug_workflow":
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Browser debug workflow untuk symptom: {arguments['symptom']}",
                ),
            ),
            PromptMessage(
                role="assistant",
                content=TextContent(
                    type="text",
                    text=_render_debug_workflow(arguments),
                ),
            ),
        ]
    raise ValueError(f"unknown prompt: {name}")
```

### Prompt Content — Templates

#### `oauth_confirmation_flow`

Service URL construction hardcoded per service (lihat `knowledge.md` §OAuth URLs).
Template text di bawah di-render ke PromptMessage content.

```python
_OAUTH_PROMPT_TEMPLATE = """\
Pattern berikut untuk handle OAuth confirmation:

1. Detect: cek response tool sebelumnya untuk error code "oauth_required"
2. Open auth URL: panggil smart_connect_browser dengan auth_url={auth_url}
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
"""
```

#### `browser_debug_workflow`

```python
_DEBUG_PROMPT_TEMPLATE = """\
Pattern investigation 4 langkah:

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
"""
```

### Testing Prompts

```python
# tests/unit/test_prompts.py
async def test_list_prompts_returns_two():
    prompts = await app.list_prompts()
    assert len(prompts) == 2
    assert {p.name for p in prompts} == {"oauth_confirmation_flow", "browser_debug_workflow"}

async def test_get_oauth_confirmation_flow():
    msgs = await app.get_prompt("oauth_confirmation_flow", {"service": "tiktok"})
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert "tiktok" in msgs[0].content.text
    assert "JANGAN auto-input password" in msgs[1].content.text

async def test_browser_debug_workflow_requires_symptom():
    with pytest.raises(ValueError):
        await app.get_prompt("browser_debug_workflow", {})
```

### Gotchas

- **Prompt content adalah plain text, bukan executable code**. LLM interpret
  sendiri. Jangan expect deterministic execution.
- **Arguments interpolation**: pakai `{argument_name}` di template. Jangan
  pakai format spec Python (`{x:.2f}`) — JSON schema tidak support.
- **Multi-turn prompt**: Prompt return multiple `PromptMessage` dengan
  role berbeda (`user` → `assistant`). Format ini sesuai `PromptMessage`
  schema (verified dari `modelcontextprotocol/specification/schema/2025-11-25/schema.json`
  `$defs/PromptMessage`).
- **Hardcoded prompt content**: untuk Phase 1, content hardcoded di source.
  Phase 2 (Strategi D) bisa download dari server (signed, ephemeral) — lihat
  `roadmap_migration.md` §Phase 2.

---

## Pause / Resume Session (User-Replacement Pattern)

> **Goal**: Agent = user replacement di browser. Saat agent detect visual
> challenge (CAPTCHA/2FA) atau decision penting (konfirmasi purchase,
> accept ToS), agent **pause** session + minta user intervene. Browser tetap
> terbuka (karena local — K2), state preserved. User solve manual, agent
> **resume** otomatis.

### `smart_session_pause(session_id, reason) -> {paused, screenshot_base64, url, hint}`

**Implementation**:
```python
@app.call_tool()
async def call_tool(name, args):
    if name == "smart_session_pause":
        session_id = args["session_id"]
        reason = args["reason"]  # captcha | 2fa | manual_review | purchase_confirmation | tos_accept | other

        session = browser_executor.get_session(session_id)
        page = session["page"]

        # Capture state
        screenshot_b64 = page.screenshot(full_page=False, type="png")
        # Convert to base64
        import base64
        screenshot_base64 = base64.b64encode(screenshot_b64).decode("ascii")

        url = page.url

        hints = {
            "captcha": "Please solve the CAPTCHA in the open browser window.",
            "2fa": "Please enter the OTP code from your authenticator app.",
            "purchase_confirmation": "Please review and confirm the purchase in the browser.",
            "tos_accept": "Please review and accept the Terms of Service.",
            "manual_review": "Your input is required to continue.",
            "other": "Manual intervention required to continue.",
        }

        # Mark session as paused (state preserved, no tab counter change)
        session["paused"] = True
        session["paused_at"] = datetime.now()
        session["pause_reason"] = reason

        # Enhance hint dengan label + position untuk multi-tab clarity
        # supaya user tidak miss komunikasi saat ada banyak tab terbuka
        label = session.get("label", "Unnamed")
        position = session.get("position", 0)
        base_hint = hints.get(reason, hints["other"])
        enhanced_hint = f"{base_hint} (Tab '{label}' at position {position})"

        return [TextContent(type="text", text=json.dumps({
            "ok": True,
            "paused": True,
            "screenshot_base64": screenshot_base64,
            "url": url,
            "hint": enhanced_hint,
            "label": label,
            "position": position,
            "session_id": session_id,
            "paused_at": session["paused_at"].isoformat(),
        }))]
```

**Penting**:
- `paused` flag di session, browser tetap hidup (tidak di-close)
- Tidak ada timeout — user boleh pause lama
- Tab counter **tidak** di-decrement saat pause (session masih aktif)

### `smart_session_resume(session_id) -> {resumed, page_handle, state, url}`

**Implementation**:
```python
@app.call_tool()
async def call_tool(name, args):
    if name == "smart_session_resume":
        session_id = args["session_id"]
        session = browser_executor.get_session(session_id)

        if not session.get("paused"):
            raise ValueError(f"session {session_id} not paused")

        # Unpause
        session["paused"] = False
        session["resumed_at"] = datetime.now()

        page = session["page"]

        # Check session validity (browser masih hidup?)
        try:
            url = page.url  # raise kalau page closed
            title = page.title()
            valid = True
        except Exception as e:
            valid = False
            url = None

        return [TextContent(type="text", text=json.dumps({
            "ok": valid,
            "resumed": valid,
            "page_handle": f"page_{session_id}" if valid else None,
            "state": "active" if valid else "session_expired",
            "url": url,
            "error": None if valid else "browser closed or session expired, please reconnect",
        }))]
```

### Pause/Resume Flow dengan Prompt

LLM flow典型 untuk CAPTCHA:
```
1. LLM panggil smart_browser_action.click(selector="button.submit")
2. Response: error code "captcha_detected" (or LLM detect via inspect)
3. LLM panggil prompt human_intervention_workflow(challenge_type="captcha")
4. Prompt instructs LLM untuk panggil smart_session_pause
5. Server return screenshot_base64 + hint
6. LLM kasih response ke user: "Saya pause session. Solve CAPTCHA di browser,
   bilang 'lanjut' kalau sudah."
7. User solve manual + bilang "lanjut"
8. LLM panggil smart_session_resume
9. Server verify session + return page_handle
10. LLM lanjut workflow (klik submit lagi, atau cek state)
```

### Testing Pause/Resume

```python
# tests/integration/test_pause_resume.py
def test_pause_keeps_session_alive():
    session = browser_executor.connect("https://example.com", "test_cred")
    sid = session["session_id"]

    # Pause
    result = await call_tool("smart_session_pause", {"session_id": sid, "reason": "captcha"})
    assert result["paused"] is True
    assert "screenshot_base64" in result

    # Session should still be queryable
    page = browser_executor.get_session(sid)["page"]
    assert page.url.startswith("https://example.com")

    # Resume
    result = await call_tool("smart_session_resume", {"session_id": sid})
    assert result["resumed"] is True

    # Tab counter should NOT have changed
    usage = license_client.get_usage()
    assert usage["tabs_used"] == 1  # same as before pause
```

### Gotchas

- **Screenshot size**: `full_page=False` lebih cepat, cukup untuk CAPTCHA
  (CAPTCHA selalu di viewport). Kalau perlu full-page, agent specify
  `full_page=True`
- **Pause tidak release browser**: memory tetap terpakai. User bisa close
  manual kalau perlu, tapi server detect via `smart_session_resume`
- **Multi-tab pause**: Phase 1 pause = pause satu session. Kalau agent
  punya multiple session, pause per-session
- **User tidak intervene**: kalau user tutup agent atau pergi, session
  tetap terbuka. `smart_close_browser` harus di-call explicit untuk cleanup