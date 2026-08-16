"""Unit tests untuk LicenseClient HTTP wrapper.

Per refactor/30_client_arch.md §License Client lines 277-315.

Tests pakai unittest.mock untuk httpx response — no real network/server.
End-to-end smoke pakai TestClient ada di /tmp/license_client_smoke.py
(juga ada test_mcp_env_browser license flow di Phase 6).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mcp_env_browser.license import (
    DEFAULT_LICENSE_SERVER_URL,
    LicenseClient,
    load_config,
    make_license_client_from_config,
)


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override HOME XDG config dir ke tmp."""
    cfg_dir = tmp_path / ".config" / "mcp-env-browser"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("MCP_LICENSE_API_KEY", raising=False)
    monkeypatch.delenv("MCP_LICENSE_SERVER_URL", raising=False)
    return cfg_dir


def _mock_response(
    status_code: int = 200, json_data: dict[str, Any] | None = None
) -> MagicMock:
    """Build mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    resp.content = (json.dumps(json_data) if json_data else "").encode()
    return resp


class TestLicenseClientCheck:
    """check() handles 200/401/403/network errors."""

    def test_check_200_valid(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="valid_key")
        mock_http = MagicMock()
        mock_http.post.return_value = _mock_response(
            200,
            {
                "valid": True,
                "plan": "dev",
                "tabs_used": 42,
                "tabs_quota": 100,
                "expires_at": "2027-01-01T00:00:00+00:00",
            },
        )
        client._http = mock_http

        result = client.check()
        assert result["valid"] is True
        assert result["plan"] == "dev"
        assert result["tabs_used"] == 42
        mock_http.post.assert_called_once_with(
            "http://test/license/check", json={"api_key": "valid_key"}
        )

    def test_check_401_invalid(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="wrong")
        mock_http = MagicMock()
        mock_http.post.return_value = _mock_response(401, {"detail": "invalid api key"})
        client._http = mock_http

        result = client.check()
        assert result["valid"] is False
        assert result["error"] == "invalid api key"

    def test_check_403_expired(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="expired")
        mock_http = MagicMock()
        mock_http.post.return_value = _mock_response(403, {"detail": "subscription expired"})
        client._http = mock_http

        result = client.check()
        assert result["valid"] is False
        assert result["error"] == "subscription expired"

    def test_check_network_error(self) -> None:
        client = LicenseClient(base_url="http://nonexistent", api_key="x")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.ConnectError("connection refused")
        client._http = mock_http

        result = client.check()
        assert result["valid"] is False
        assert "network" in result["error"]

    def test_check_unexpected_response(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="x")
        mock_http = MagicMock()
        mock_http.post.return_value = _mock_response(200, "not a dict")
        client._http = mock_http

        result = client.check()
        assert result["valid"] is False
        assert "unexpected" in result["error"]


class TestLicenseClientIncrement:
    """increment() handles 200/401/403/429/network errors."""

    def test_increment_200(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="k")
        mock_http = MagicMock()
        mock_http.post.return_value = _mock_response(
            200,
            {
                "ok": True,
                "tabs_used": 5,
                "tabs_quota_remaining": 995,
            },
        )
        client._http = mock_http

        result = client.increment(amount=1)
        assert result["ok"] is True
        assert result["tabs_used"] == 5
        assert result["tabs_quota_remaining"] == 995

    def test_increment_quota_exceeded(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="k")
        mock_http = MagicMock()
        mock_http.post.return_value = _mock_response(
            429,
            {
                "detail": {
                    "detail": "tab quota exceeded",
                    "tabs_used": 10000,
                    "tabs_quota": 10000,
                }
            },
        )
        client._http = mock_http

        result = client.increment(1)
        assert result["ok"] is False
        assert result["quota_exceeded"] is True
        assert result["detail"]["tabs_used"] == 10000

    def test_increment_invalid_key(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="wrong")
        mock_http = MagicMock()
        mock_http.post.return_value = _mock_response(401, {"detail": "invalid api key"})
        client._http = mock_http

        result = client.increment(1)
        assert result["ok"] is False

    def test_increment_network(self) -> None:
        client = LicenseClient(base_url="http://test", api_key="k")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.ConnectError("network")
        client._http = mock_http

        result = client.increment(1)
        assert result["ok"] is False


class TestLicenseClientConstruction:
    """Constructor defaults + env var override + URL trailing slash."""

    def test_default_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_LICENSE_SERVER_URL", raising=False)
        client = LicenseClient(api_key="k")
        assert client.base_url == DEFAULT_LICENSE_SERVER_URL

    def test_env_var_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_LICENSE_SERVER_URL", "http://envhost:9999")
        client = LicenseClient(api_key="k")
        assert client.base_url == "http://envhost:9999"

    def test_trailing_slash_trimmed(self) -> None:
        client = LicenseClient(base_url="http://host:9999/", api_key="k")
        assert client.base_url == "http://host:9999"

    def test_default_timeout(self) -> None:
        client = LicenseClient(api_key="k")
        assert client._timeout == 2.0  # per K6 fail-fast per 20_license_server.md line 105

    def test_close(self) -> None:
        client = LicenseClient(api_key="k")
        mock_http = MagicMock()
        client._http = mock_http
        client.close()
        mock_http.close.assert_called_once()


class TestConfigLoader:
    """load_config reads ~/.config/mcp-env-browser/config.json + env overrides."""

    def test_load_empty_default(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = load_config()
        assert cfg == {}

    def test_load_from_file(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tmp_config_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = tmp_config_dir / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "license_server_url": "http://file-host:8765",
                    "license_api_key": "hex_from_file",
                    "vault_backend": "encrypted_json",
                }
            )
        )
        monkeypatch.delenv("MCP_LICENSE_API_KEY", raising=False)
        monkeypatch.delenv("MCP_LICENSE_SERVER_URL", raising=False)
        cfg = load_config()
        assert cfg["license_server_url"] == "http://file-host:8765"
        assert cfg["license_api_key"] == "hex_from_file"
        assert cfg["vault_backend"] == "encrypted_json"

    def test_env_overrides_file(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tmp_config_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = tmp_config_dir / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "license_server_url": "http://file-host:8765",
                    "license_api_key": "file_key",
                }
            )
        )
        monkeypatch.setenv("MCP_LICENSE_API_KEY", "env_key_wins")
        monkeypatch.setenv("MCP_LICENSE_SERVER_URL", "http://env-host:9999")

        cfg = load_config()
        assert cfg["license_api_key"] == "env_key_wins"  # env wins
        assert cfg["license_server_url"] == "http://env-host:9999"


class TestFactory:
    """make_license_client_from_config builds client from config."""

    def test_make_client(self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        tmp_config_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = tmp_config_dir / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "license_server_url": "http://factory-host:8765",
                    "license_api_key": "factory_key",
                }
            )
        )
        monkeypatch.delenv("MCP_LICENSE_API_KEY", raising=False)
        monkeypatch.delenv("MCP_LICENSE_SERVER_URL", raising=False)

        client = make_license_client_from_config()
        assert client.base_url == "http://factory-host:8765"
        assert client.api_key == "factory_key"
