"""LicenseClient — HTTP wrapper for license server endpoints (Phase 4).

Per refactor/30_client_arch.md §License Client + knowledge.md §5 FastAPI pattern.

Used by:
- BrowserExecutor (Phase 5) — license check + counter increment before new_page
- MCP tool server (Phase 6) — could be used for license introspection
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from mcp_env_browser import DEFAULT_LICENSE_SERVER_URL

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 2.0  # seconds (per K6 fail-fast per 20_license_server.md line 105)


class LicenseClient:
    """HTTP wrapper for license-server endpoints (Phase 4).

    Endpoints:
    - POST /license/check — returns {valid, plan, tabs_used, tabs_quota, expires_at}
    - POST /tab/increment — returns {ok, tabs_used, tabs_quota_remaining} or 429
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("MCP_LICENSE_SERVER_URL")
            or DEFAULT_LICENSE_SERVER_URL
        ).rstrip("/")
        self._api_key = (
            api_key or os.environ.get("MCP_LICENSE_API_KEY") or ""
        )
        self._timeout = timeout
        self._http = httpx.Client(timeout=timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    def check(self) -> dict[str, object]:
        """Validate API key. Returns dict with valid/plan/tabs_used/tabs_quota/expires_at.

        Errors are returned as dict (not raised) so caller can decide policy.
        Network/HTTP errors: {"valid": False, "error": "..."}
        401: {"valid": False, "error": "invalid api key"}
        403: {"valid": False, "error": "subscription expired"}
        """
        try:
            resp = self._http.post(
                f"{self._base_url}/license/check",
                json={"api_key": self._api_key},
            )
        except httpx.HTTPError as e:
            logger.warning("license check network error: %s", e)
            return {"valid": False, "error": f"network: {e}"}

        if resp.status_code == 200:
            data_resp: object = resp.json()
            if not isinstance(data_resp, dict):
                return {"valid": False, "error": "unexpected response"}
            data: dict[str, object] = data_resp
            data.setdefault("valid", True)
            return data
        if resp.status_code == 401:
            return {"valid": False, "error": "invalid api key"}
        if resp.status_code == 403:
            return {"valid": False, "error": "subscription expired"}
        return {"valid": False, "error": f"http {resp.status_code}: {resp.text}"}

    def increment(self, amount: int = 1) -> dict[str, object]:
        """Atomically increment tab counter.

        Returns:
        - 200: {"ok": True, "tabs_used", "tabs_quota_remaining"}
        - 401/403: {"ok": False, "error": "..."}
        - 429 quota exceeded: {"ok": False, "quota_exceeded": True, "detail": {...}}
        - network: {"ok": False, "error": "network: ..."}
        """
        try:
            resp = self._http.post(
                f"{self._base_url}/tab/increment",
                json={"api_key": self._api_key, "amount": amount},
            )
        except httpx.HTTPError as e:
            logger.warning("license increment network error: %s", e)
            return {"ok": False, "error": f"network: {e}"}

        if resp.status_code == 200:
            data_resp = resp.json()
            if not isinstance(data_resp, dict):
                return {"ok": False, "error": "unexpected response"}
            data: dict[str, object] = data_resp
            data.setdefault("ok", True)
            return data
        if resp.status_code == 401:
            return {"ok": False, "error": "invalid api key"}
        if resp.status_code == 403:
            return {"ok": False, "error": "subscription expired"}
        if resp.status_code == 429:
            try:
                detail = resp.json().get("detail", {})
            except Exception:
                detail = {}
            return {
                "ok": False,
                "quota_exceeded": True,
                "detail": detail,
            }
        return {"ok": False, "error": f"http {resp.status_code}: {resp.text}"}

    def close(self) -> None:
        """Close underlying HTTP client (caller responsibility)."""
        self._http.close()

    # --- context manager support ---
    def __enter__(self) -> LicenseClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Config loader — reads ~/.config/mcp-env-browser/config.json
# Per refactor/30_client_arch.md §Config File line 322-333
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_DIR = Path("~/.config/mcp-env-browser")
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


def load_config() -> dict[str, object]:
    """Load config from ~/.config/mcp-env-browser/config.json.

    Returns empty dict if file doesn't exist (Phase 8 init wizard will create).

    Per 30_client_arch.md §Cross-cutting Config File:
    {
      "license_server_url": "http://localhost:8765",
      "license_api_key": "hex_32_chars",
      "vault_backend": "auto",
      "browser_headless": false,
      "log_level": "INFO"
    }

    Env var overrides (set precedence):
    - MCP_LICENSE_SERVER_URL > license_server_url
    - MCP_LICENSE_API_KEY > license_api_key
    - MCP_VAULT_BACKEND > vault_backend
    """
    config: dict[str, object] = {}
    path = DEFAULT_CONFIG_FILE.expanduser()
    if path.exists():
        import json

        with open(path) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            config = loaded

    # Env var overrides (env wins over file)
    overrides = {
        "license_server_url": "MCP_LICENSE_SERVER_URL",
        "license_api_key": "MCP_LICENSE_API_KEY",
        "vault_backend": "MCP_VAULT_BACKEND",
        "browser_headless": "MCP_BROWSER_HEADLESS",
        "log_level": "MCP_LOG_LEVEL",
    }
    for key, env_var in overrides.items():
        env_val = os.environ.get(env_var)
        if env_val:
            config[key] = env_val

    return config


def make_license_client_from_config() -> LicenseClient:
    """Build LicenseClient from config (file + env vars)."""
    cfg = load_config()
    return LicenseClient(
        base_url=cfg.get("license_server_url"),  # type: ignore[arg-type]
        api_key=cfg.get("license_api_key"),  # type: ignore[arg-type]
    )
