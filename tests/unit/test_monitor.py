"""Unit tests untuk Web Monitoring Companion (Phase 7).

Per refactor/45_monitoring.md (full spec).

Strategy: FastAPI TestClient + mocked BrowserExecutor (MagicMock). No real
browser session — we just exercise HTTP endpoint → BrowserExecutor wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mcp_env_browser.monitor import app, set_browser_executor


@pytest.fixture
def fake_executor() -> MagicMock:
    be = MagicMock()
    be.list_sessions.return_value = [
        {
            "session_id": "abc",
            "label": "TikTok Login",
            "position": 0,
            "url": "https://www.tiktok.com/login",
            "status": "active",
            "age_seconds": 12,
            "last_screenshot_b64": "ZmFrZQ==",
        },
        {
            "session_id": "def",
            "label": "GCP Billing",
            "position": 1,
            "url": "https://console.cloud.google.com/billing",
            "status": "paused",
            "age_seconds": 60,
            "last_screenshot_b64": None,
        },
    ]
    be.focus_session.return_value = None
    return be


@pytest.fixture
def client(fake_executor: MagicMock) -> TestClient:
    set_browser_executor(fake_executor)
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestIndexEndpoint:
    def test_index_returns_html(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "mcp-env-browser Monitor" in resp.text
        assert "<script>" in resp.text
        assert "/api/sessions" in resp.text
        assert "setInterval(refresh, 2000)" in resp.text


class TestListSessionsEndpoint:
    def test_list_sessions_default_include_screenshot(
        self, client: TestClient, fake_executor: MagicMock
    ) -> None:
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["session_id"] == "abc"
        assert data[0]["last_screenshot_b64"] == "ZmFrZQ=="
        fake_executor.list_sessions.assert_called_once_with(include_screenshot=True)

    def test_list_sessions_include_screenshot_false(
        self, client: TestClient, fake_executor: MagicMock
    ) -> None:
        resp = client.get("/api/sessions?include_screenshot=false")
        assert resp.status_code == 200
        fake_executor.list_sessions.assert_called_once_with(include_screenshot=False)


class TestFocusSessionEndpoint:
    def test_focus_session_ok(
        self, client: TestClient, fake_executor: MagicMock
    ) -> None:
        resp = client.post("/api/sessions/abc/focus")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        fake_executor.focus_session.assert_called_once_with("abc")

    def test_focus_session_not_found(
        self, client: TestClient, fake_executor: MagicMock
    ) -> None:
        fake_executor.focus_session.side_effect = KeyError("session missing not found")
        resp = client.post("/api/sessions/missing/focus")
        assert resp.status_code == 404
        assert "missing" in resp.json()["detail"]


class TestBrowserExecutorNotInitialized:
    def test_list_sessions_returns_503_when_not_set(self) -> None:
        """Without set_browser_executor(), endpoints return 503."""
        # Use a fresh client without injecting executor
        from mcp_env_browser import monitor

        monitor.browser_executor = None
        c = TestClient(monitor.app)
        resp = c.get("/api/sessions")
        assert resp.status_code == 503
        assert "not initialized" in resp.json()["detail"]

    def test_focus_session_returns_503_when_not_set(self) -> None:
        from mcp_env_browser import monitor

        monitor.browser_executor = None
        c = TestClient(monitor.app)
        resp = c.post("/api/sessions/abc/focus")
        assert resp.status_code == 503
