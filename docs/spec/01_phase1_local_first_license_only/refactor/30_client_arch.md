# 30 — Client Architecture (Local-First)

> Detail teknis untuk `src/mcp_env_browser/vault/` dan
> `src/mcp_env_browser/browser/`.

---

## Vault Module

```
src/mcp_env_browser/vault/
├── __init__.py            # VaultBackend Protocol + factory
├── secretstorage.py       # Linux libsecret adapter (primary)
└── encrypted_json.py      # Fallback / headless server
```

### `VaultBackend` Protocol

```python
from typing import Protocol, Optional

class VaultBackend(Protocol):
    def set(self, key: str, value: bytes, attributes: dict) -> None: ...
    def get(self, key: str) -> Optional[bytes]: ...
    def delete(self, key: str) -> None: ...
    def list_keys(self, filter_text: Optional[str] = None) -> list[dict]: ...
    def is_unlocked(self) -> bool: ...
```

### Factory

```python
def get_vault_backend() -> VaultBackend:
    """Select backend based on env + availability."""
    backend_pref = os.environ.get("MCP_VAULT_BACKEND", "auto")

    if backend_pref == "auto":
        try:
            import secretstorage
            conn = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(conn)
            if collection.is_locked():
                collection.unlock()
            return SecretStorageBackend()
        except Exception as e:
            logger.warning(f"libsecret unavailable: {e}, fallback to encrypted_json")
            return EncryptedJSONBackend()

    if backend_pref == "secretstorage":
        return SecretStorageBackend()
    if backend_pref == "encrypted_json":
        return EncryptedJSONBackend()

    raise ValueError(f"unknown backend: {backend_pref}")
```

### `SecretStorageBackend` (Linux primary)

Pakai `python-secretstorage` library. Setiap credential disimpan sebagai
**item collection** dengan:

| Field | Value |
|---|---|
| Label | `{key}` (e.g., `"tiktok_user_alice"`) |
| Attributes | `{"app": "mcp-env-browser", "type": "<credential_type>", "key": "<key>"}` |
| Secret | `json.dumps(value).encode()` (plaintext bytes — libsecret encrypt at OS level) |

```python
class SecretStorageBackend:
    def __init__(self):
        import secretstorage
        self._conn = secretstorage.dbus_init()
        self._collection = secretstorage.get_default_collection(self._conn)
        if self._collection.is_locked():
            self._collection.unlock()

    def set(self, key, value, attributes):
        attrs = {"app": "mcp-env-browser", "key": key, **attributes}
        secret = json.dumps(value).encode()

        # Check existing
        for item in self._collection.search_items(attrs):
            item.set_secret(secret)
            return
        # Create new
        self._collection.create_item(label=key, attributes=attrs, secret=secret)

    def get(self, key):
        for item in self._collection.search_items({"app": "mcp-env-browser", "key": key}):
            return json.loads(item.get_secret().decode())
        return None

    def delete(self, key):
        for item in self._collection.search_items({"app": "mcp-env-browser", "key": key}):
            item.delete()
            return

    def list_keys(self, filter_text=None):
        keys = []
        for item in self._collection.search_items({"app": "mcp-env-browser"}):
            attrs = item.get_attributes()
            if filter_text and filter_text not in attrs.get("key", ""):
                continue
            keys.append({
                "key": attrs.get("key"),
                "type": attrs.get("type"),
                "summary": attrs.get("summary", "***"),
            })
        return keys

    def is_unlocked(self):
        return not self._collection.is_locked()
```

### `EncryptedJSONBackend` (fallback)

Untuk environment tanpa D-Bus (headless server, SSH tanpa session).
File-based, encrypted dengan **passphrase dari env var**:

```python
class EncryptedJSONBackend:
    def __init__(self):
        self._path = Path(os.environ.get("MCP_VAULT_PATH", "~/.local/share/mcp-env-browser/vault.json"))
        self._passphrase = os.environ["MCP_VAULT_PASSPHRASE"]  # required
        # Derive key via scrypt
        salt = self._path.with_suffix(".salt").read_bytes() if self._path.exists() else os.urandom(16)
        self._key = hashlib.scrypt(self._passphrase.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)

    # set/get/delete/list_keys/is_unlocked — symmetric to SecretStorageBackend
    # Encryption: AES-GCM via cryptography library
```

### Security Notes

- **SecretStorageBackend**: OS-level encryption, depends on `gnome-keyring`
  atau `kwallet` daemon. Key derivation & access control = OS handle.
- **EncryptedJSONBackend**: passphrase harus diset via env var. **TIDAK boleh**
  hardcode atau default ke empty.
- **MCP tool tidak pernah return plaintext** ke agent — value dipakai
  internal (e.g., untuk login), bukan di-return sebagai TextContent.

---

## Browser Module

```
src/mcp_env_browser/browser/
├── __init__.py            # BrowserExecutor class + factory
├── executor.py            # Playwright wrapper + per-tab counter
└── cdp.py                 # CDP helpers (Console/Network/DOM)
```

### `BrowserExecutor`

```python
class BrowserExecutor:
    def __init__(self, license_client, vault):
        self._license_client = license_client
        self._vault = vault
        self._playwright = None
        self._browser = None
        self._sessions: dict[str, dict] = {}  # session_id -> {context, page, ...}

    def _ensure_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=False)  # local user

    def connect(self, target: str, credential_key: str) -> dict:
        # 1. License check (real-time, K6)
        license_status = self._license_client.check()
        if not license_status["valid"]:
            raise LicenseInvalid(license_status)

        # 2. Increment counter (BEFORE opening tab, K6 enforcement)
        increment = self._license_client.increment(amount=1)
        if not increment["ok"]:
            raise QuotaExceeded(increment)

        # 3. Get credential from vault (no plaintext return)
        cred = self._vault.get(credential_key)
        if cred is None:
            raise VaultKeyNotFound(credential_key)

        # 4. Launch + login
        self._ensure_browser()
        context = self._browser.new_context()
        page = context.new_page()  # ← counted as 1 tab (already incremented)
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {"context": context, "page": page}

        # 5. Hardcoded login flow per target (Phase 1)
        # Phase 2: workflow scripts from server
        self._auto_login(page, target, cred)

        return {"session_id": session_id, "page_handle": f"page_{session_id}"}

    def action(self, session_id, action, **kwargs):
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        page = self._sessions[session_id]["page"]
        # dispatch to action handler
        return self._dispatch_action(page, action, **kwargs)

    def close(self, session_id=None):
        if session_id is None:
            for sid in list(self._sessions.keys()):
                self.close(sid)
            if self._browser:
                self._browser.close()
                self._playwright.stop()
            return
        if session_id in self._sessions:
            self._sessions[session_id]["context"].close()
            del self._sessions[session_id]
```

### `cdp.py` — Console/Network/DOM helpers

```python
class CDPHelpers:
    def __init__(self, page):
        self._client = page.context.new_cdp_session(page)

    def enable_console(self):
        self._client.send("Console.enable")
        self._messages = []
        self._client.on("Console.messageAdded", lambda e: self._messages.append(e))

    def get_console_log(self, level=None):
        if level:
            return [m for m in self._messages if m["message"]["level"] == level]
        return self._messages

    def enable_network(self):
        self._client.send("Network.enable")
        self._requests = {}
        self._client.on("Network.requestWillBeSent", self._on_request)
        self._client.on("Network.responseReceived", self._on_response)

    def _on_request(self, event):
        self._requests[event["requestId"]] = {
            "url": event["request"]["url"],
            "method": event["request"]["method"],
            "started_at": time.time(),
        }

    def _on_response(self, event):
        rid = event["requestId"]
        if rid in self._requests:
            self._requests[rid]["status"] = event["response"]["status"]
            self._requests[rid]["duration_ms"] = int((time.time() - self._requests[rid]["started_at"]) * 1000)

    def get_network_log(self, filter_text=None):
        items = [r for r in self._requests.values() if not filter_text or filter_text in r["url"]]
        return items

    def inspect_element(self, selector):
        doc = self._client.send("DOM.getDocument")
        node_id = self._client.send("DOM.querySelector", {
            "nodeId": doc["root"]["nodeId"],
            "selector": selector,
        })["nodeId"]
        attrs = self._client.send("DOM.getAttributes", {"nodeId": node_id})
        computed = self._client.send("CSS.getComputedStyle", {"nodeId": node_id})
        return {
            "tag": "...",  # parse from nodeName
            "attrs": self._parse_attrs(attrs),
            "computed_style": self._parse_computed(computed),
            "children_count": self._client.send("DOM.getChildNodeCount", {"nodeId": node_id})["childNodeCount"],
        }
```

---

## License Client

```
src/mcp_env_browser/license/
├── __init__.py
└── client.py
```

```python
import httpx
import os

class LicenseClient:
    def __init__(self, base_url: str = None, api_key: str = None, timeout: float = 2.0):
        self._base_url = base_url or os.environ["MCP_LICENSE_SERVER_URL"]
        self._api_key = api_key or os.environ["MCP_LICENSE_API_KEY"]
        self._timeout = timeout
        self._http = httpx.Client(timeout=timeout)

    def check(self) -> dict:
        try:
            r = self._http.post(f"{self._base_url}/license/check", json={"api_key": self._api_key})
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            return {"valid": False, "error": str(e)}

    def increment(self, amount: int = 1) -> dict:
        try:
            r = self._http.post(f"{self._base_url}/tab/increment", json={"api_key": self._api_key, "amount": amount})
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                return {"ok": False, "error": "quota_exceeded", "detail": e.response.json()}
            return {"ok": False, "error": str(e)}
        except httpx.HTTPError as e:
            return {"ok": False, "error": "network", "detail": str(e)}
```

---

## Cross-cutting

### Config File

Path: `~/.config/mcp-env-browser/config.json`

```json
{
  "license_server_url": "http://localhost:8765",
  "license_api_key": "hex_32_chars",
  "vault_backend": "auto",
  "browser_headless": false,
  "log_level": "INFO"
}
```

### Logging

- Library: `structlog`
- Output: stderr (NOT stdout — break MCP protocol)
- File: `~/.local/share/mcp-env-browser/logs/{date}.log` (rotated)
- Structured fields: `tool`, `session_id`, `duration_ms`, `error`

### Dependencies (pyproject.toml)

```toml
[project]
name = "mcp-env-browser"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "mcp>=0.5",
    "httpx>=0.25",
    "playwright>=1.40",
    "structlog>=24.1",
    "secretstorage>=3.3 ; sys_platform == 'linux'",
    "cryptography>=41.0",  # for encrypted_json backend
]

[project.optional-dependencies]
server = ["fastapi>=0.100", "uvicorn[standard]>=0.23", "pydantic>=2.0", "alembic>=1.13"]

dev = [
    "pytest>=7.4",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.1",
    "httpx>=0.25",  # also used by tests
    "mypy>=1.7",
    "ruff>=0.1",
]

[project.scripts]
mcp-env-browser = "mcp_env_browser.cli:cli"
mcp-env-browser-license-server = "license_server.server:run"
```