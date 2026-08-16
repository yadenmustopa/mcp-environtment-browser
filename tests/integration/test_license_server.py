"""Integration tests untuk license_server FastAPI endpoints.

Menggunakan FastAPI TestClient (no real HTTP server, no port binding).
Tests pakai tmp_path untuk isolated DB per test.

Per spec §6.5 + 20_license_server.md.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from license_server.server import app


@pytest.fixture
def isolated_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, Path], None, None]:
    """Provide FastAPI TestClient with isolated DB per test.

    Returns (client, db_path) — db_path is the temp file the client used.
    """
    db_path = tmp_path / "int_license.sqlite3"
    monkeypatch.setenv("MCP_LICENSE_DB_PATH", str(db_path))
    # Also enable admin endpoint for registration tests
    monkeypatch.setenv("MCP_ADMIN_TOKEN", "test-admin-token")
    # Reset FastAPI app state by triggering lifespan
    with TestClient(app) as client:
        yield client, db_path


class TestHealthEndpoint:
    """GET /health — no auth."""

    def test_health_returns_ok(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "version": "0.1.0"}

    def test_health_no_auth_required(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        """No X-Admin-Token / X-API-Key needed."""
        client, _ = isolated_client
        r = client.get("/health", headers={})  # no headers
        assert r.status_code == 200


class TestLicenseCheck:
    """POST /license/check."""

    def test_invalid_key_returns_401(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post("/license/check", json={"api_key": "invalid"})
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid api key"

    def test_valid_key_returns_200(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        # Register user first
        r = client.post(
            "/license/register",
            json={"email": "u@example.com", "plan": "dev", "tabs_quota": 100},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert r.status_code == 200
        api_key = r.json()["api_key"]

        r = client.post("/license/check", json={"api_key": api_key})
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["plan"] == "dev"
        assert data["tabs_used"] == 0
        assert data["tabs_quota"] == 100


class TestLicenseRegister:
    """POST /license/register (admin)."""

    def test_register_requires_admin_token(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "u@example.com"},
        )
        assert r.status_code == 401  # token header missing
        assert "X-Admin-Token" in r.json()["detail"]

    def test_register_wrong_admin_token_403(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "u@example.com"},
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "invalid admin token"

    def test_register_admin_disabled_when_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_LICENSE_DB_PATH", str(tmp_path / "x.sqlite3"))
        monkeypatch.delenv("MCP_ADMIN_TOKEN", raising=False)
        with TestClient(app) as c:
            r = c.post(
                "/license/register",
                json={"email": "u@example.com"},
                headers={"X-Admin-Token": "any"},
            )
            assert r.status_code == 403
            assert "disabled" in r.json()["detail"]

    def test_register_validates_email(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "not-an-email"},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert r.status_code == 422  # pydantic validation

    def test_register_duplicate_email_409(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "dupe@example.com"},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert r.status_code == 200
        r = client.post(
            "/license/register",
            json={"email": "dupe@example.com"},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert r.status_code == 409
        assert "already registered" in r.json()["detail"]

    def test_register_returns_hex_api_key(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "key@example.com"},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert r.status_code == 200
        api_key = r.json()["api_key"]
        assert len(api_key) == 64
        assert all(c in "0123456789abcdef" for c in api_key)


class TestTabIncrement:
    """POST /tab/increment — atomic counter."""

    def test_increment_valid_key(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "inc@example.com", "tabs_quota": 100},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        api_key = r.json()["api_key"]
        r = client.post(
            "/tab/increment", json={"api_key": api_key, "amount": 5}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["tabs_used"] == 5
        assert data["tabs_quota_remaining"] == 95

    def test_increment_invalid_key_401(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/tab/increment", json={"api_key": "doesnt-exist", "amount": 1}
        )
        assert r.status_code == 401

    def test_increment_quota_exceeded_429(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "max@example.com", "tabs_quota": 3},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        api_key = r.json()["api_key"]
        # Use up the quota
        for _ in range(3):
            r = client.post("/tab/increment", json={"api_key": api_key, "amount": 1})
            assert r.status_code == 200
        # Next request: 429
        r = client.post("/tab/increment", json={"api_key": api_key, "amount": 1})
        assert r.status_code == 429
        detail = r.json()["detail"]
        # FastAPI wraps HTTPException detail into a JSON object
        assert detail["tabs_used"] == 3
        assert detail["tabs_quota"] == 3

    def test_increment_default_amount_is_1(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "def@example.com", "tabs_quota": 10},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        api_key = r.json()["api_key"]
        # No `amount` field → default 1
        r = client.post("/tab/increment", json={"api_key": api_key})
        assert r.status_code == 200
        assert r.json()["tabs_used"] == 1

    def test_increment_negative_amount_422(
        self, isolated_client: tuple[TestClient, Path]
    ) -> None:
        client, _ = isolated_client
        r = client.post(
            "/license/register",
            json={"email": "neg@example.com"},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        api_key = r.json()["api_key"]
        r = client.post(
            "/tab/increment", json={"api_key": api_key, "amount": -5}
        )
        assert r.status_code == 422  # pydantic validation (ge=0)
