# Knowledge — Phase 1 Reuse Catatan

> Catatan infrastruktur yang sudah ada di sistem Anda dan bisa di-reuse,
> bukan di-rebuild.

---

## 1. `cua-driver` 0.19.2 — Desktop/Window Control

**Lokasi**: `/home/denevill/.local/bin/cua-driver`
**Subcommands**: `mcp`, `list-tools`, `describe`, `call`, `serve`, `doctor`, `browser-approve`, `manifest`

### Cara pakai di Phase 1

- **Desktop window control** (kalau user ingin lihat browser local visible):
  `cua-driver serve` + connect via MCP `cua_browser_*` actions
- **Health check**: `cua-driver doctor` untuk diagnose saat GUI test gagal

### Kapan **TIDAK** dipakai

- Kalau agent mau **headless** Playwright (scrape tanpa UI) — pakai
  Playwright Python langsung, tidak perlu cua-driver
- Kalau target adalah **browser farm di server** — itu Strategi D/Phase 2+

### Gotcha

- `cua-driver` punya **permission gate** (Accessibility + Screen Recording).
  Di Linux pakai X11/Wayland — kalau X server tidak ada, headless Playwright
  lebih reliable
- `cua_browser_*` actions pakai typed semantic ref — agent flow cukup ribet
  kalau scrape banyak halaman. Untuk Phase 1 lebih simple pakai Playwright
  Python dengan selector CSS langsung

---

## 2. libsecret / Secret Service API — Credential Storage

**Library tersedia di OS**: `libsecret-1.so.0` di `/usr/lib/x86_64-linux-gnu/`
**Daemon**: `gnome-keyring-daemon` running (PID 4180, August 15)
**Python binding**: `python3-secretstorage` belum terinstall — perlu di-install

### Cara pakai di Phase 1

```bash
pip install secretstorage keyring
```

```python
import secretstorage

conn = secretstorage.dbus_init()  # di Linux pakai D-Bus
collection = secretstorage.get_default_collection(conn)

# Set
collection.create_item(
    "tiktok_alice_password",
    {"app": "mcp-env-browser", "type": "username_password"},
    b"hunter2_encrypted_bytes"
)

# Get
for item in collection.search_items({"app": "mcp-env-browser"}):
    if item.get_label() == "tiktok_alice_password":
        secret = item.get_secret()
```

### Cross-platform adapter (untuk Phase 2)

```python
# vault/backends/__init__.py
class VaultBackend(Protocol):
    def set(self, key: str, value: bytes, attributes: dict) -> None: ...
    def get(self, key: str, attributes: dict) -> bytes | None: ...
    def delete(self, key: str, attributes: dict) -> None: ...
    def list_keys(self, attributes_filter: dict) -> list[str]: ...

# vault/backends/secretstorage.py (Linux)
# vault/backends/keychain.py (macOS — Phase 2)
# vault/backends/wincred.py (Windows — Phase 2)
# vault/backends/encrypted_json.py (fallback / Phase 1 dev tanpa D-Bus)
```

### Gotcha

- `secretstorage` butuh **D-Bus session bus**. Di SSH tanpa session, gagal
- `gnome-keyring-daemon` harus unlock (kalau auto-unlock tidak aktif, user
  harus input password saat login pertama). Untuk headless server, tambah
  `EncryptedJSONBackend` sebagai fallback
- **Password per-user, per-machine**. Backup credential harus via mekanisme
  terpisah (export encrypted blob, simpan ke encrypted USB)

---

## 3. Playwright (Python) — Browser Automation

**Install**: `pip install playwright && python -m playwright install chromium`

### Cara pakai di Phase 1

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()  # ← INI yang dihitung per-tab
    page.goto("https://www.tiktok.com/@alice")
    ...
```

### CDP access untuk Console/Network/DOM

```python
client = context.new_cdp_session(page)
client.send("Console.enable")
client.send("Network.enable")
client.send("DOM.enable")

# Console log
client.on("Console.messageAdded", lambda event: print(event))

# Network log
client.on("Network.requestWillBeSent", lambda event: print(event))

# DOM inspect
doc = client.send("DOM.getDocument")
node_id = client.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": ".username"})
```

### Gotcha

- **WebGL/canvas fingerprint blocking**: TikTok/Google agresif block headless.
  Fase 1: pakai `headless=False` di local development (atau `--disable-blink-features=AutomationControlled` flag)
- **Per-tab counter** harus dihitung di wrapper kita, BUKAN dari Playwright
  internal — karena `browser.new_context()` dan `context.new_page()` keduanya
  bisa di-instance. Definisi kita: "1 tab = 1 page yang dipakai untuk
  interaksi user/agent"
- **Memory leak**: setiap page harus di-close explicit, kalau tidak memory
  naik. Phase 1 pakai context manager `with` untuk guarantee cleanup

---

## 4. MCP Python SDK — stdio Transport

**Install**: `pip install mcp`

### Pattern server

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("mcp-env-browser")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [...]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ...

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
```

### Gotcha

- MCP pakai **async** — pastikan semua handler `async def`. Sync Playwright
  harus di-wrap di `asyncio.to_thread()` atau pakai Playwright async API
- Stdio buffering: kalau print ke stdout dari client, **break MCP protocol**.
  Pakai logger stderr atau structlog
- **Single client**: MCP stdio default 1 client per server. Multi-client
  pakai SSE transport (Phase 3)

---

## 5. FastAPI — License Server

**Install**: `pip install fastapi uvicorn pydantic`

### Pattern minimal

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class LicenseCheck(BaseModel):
    api_key: str

@app.post("/license/check")
async def license_check(body: LicenseCheck):
    row = db.get_user_by_api_key(body.api_key)
    if not row:
        raise HTTPException(401, "invalid api key")
    if row["expires_at"] < now():
        raise HTTPException(403, "subscription expired")
    return {
        "valid": True,
        "plan": row["plan"],
        "tabs_used": row["tabs_used"],
        "tabs_quota": row["tabs_quota"],
        "expires_at": row["expires_at"].isoformat(),
    }
```

### Gotcha

- **SQLite + uvicorn multi-worker** = race condition. Phase 1 pakai 1 worker
- **CORS**: license server tidak butuh CORS (server-to-server only)
- **API key in body, bukan header** — sederhana untuk Phase 1, nanti rotate
  ke Bearer token di Phase 2

---

## 6. PyInstaller — Distribusi Binary

**Install**: `pip install pyinstaller`

### Pattern

```bash
pyinstaller --onefile --name mcp-env-browser src/mcp_env_browser/cli.py
```

### Gotcha

- **Size**: PyInstaller bundle ~50-100MB karena embed Python interpreter +
  Playwright. Acceptable untuk desktop tool
- **Chromium binary tidak auto-bundle**. User tetap harus run
  `playwright install chromium` post-install, atau kita bundle manual
- **Anti-reverse engineering**: PyInstaller bisa di-extract pakai
  `pyinstxtractor`. Kode .pyc visible. Strategi A sadar akan ini — K5 dipenuhi
  via **bisnis model (license gate)**, bukan technical lock. Dokumentasi
  keputusan ada di `refactor/90_decisions_log.md` K5

---

## 7. Smart Agent — Sister Project (NOT REUSE)

**Path**: `/mnt/nvme/my-job/github/BharataCorp/smart_agent`

### Yang TIDAK di-reuse

- **Tidak coupled** — repo ini berdiri sendiri, bukan submodule smart_agent
- **Tidak share database** — license DB independent
- **Tidak share credential vault** — schema berbeda (smart_agent pakai
  `~/.config/antigravity-profiles/` untuk Chrome profile, kita pakai
  libsecret untuk generic K/V)

### Yang bisa di-reuse (untuk UX consistency)

- **Spec v3 pattern** (docs/spec/{slug}/spec.md + state.json + knowledge.md +
  refactor/) — kita adopsi pattern yang sama
- **WebSocket/SSE patterns** — kalau Phase 3 butuh dashboard, copy pattern
  dari smart_agent

---

## 8. Reuse Decision Matrix

| Kebutuhan | Reuse | Build New | Alasan |
|---|---|---|---|
| Desktop/Window control | cua-driver | — | Sudah ada |
| Credential storage Linux | libsecret | — | OS-native, secure |
| Credential storage Win/Mac | — | Adapter Phase 2 | Cross-platform = future |
| Browser automation | — | Playwright wrapper | Custom per-tab counter |
| MCP protocol | mcp SDK | — | Standard |
| License server | — | FastAPI minimal | Simple, butuh kontrol penuh |
| Credential encryption | libsecret | — | OS handles |
| Master key KDF | — | Phase 2 | Tidak untuk Phase 1 |
| Dashboard UI | — | Phase 3 | Bukan Phase 1 scope |
| CLI | — | Click | Familiar Python pattern |
| Install script | — | Bash idempotent | Mirror smart_agent style |