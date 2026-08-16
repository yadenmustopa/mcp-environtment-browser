"""Unit tests untuk BrowserExecutor (Phase 5).

Per refactor/30_client_arch.md §Browser Module + refactor/10_mcp_server.md §MCP Tools.

Strategy: mock `playwright.sync_api` module-level via `sys.modules` injection
sehingga BrowserExecutor._ensure_browser() lazy import ambil mock kita — no
real Chromium launch di CI.

Tests cover:
1. Constructor + lazy _ensure_browser()
2. connect() — happy path (vault.get → license.check → increment → new_page → goto)
3. connect() — credential not found → ValueError
4. connect() — license invalid → PermissionError
5. connect() — quota exceeded → PermissionError
6. connect() — multiple sessions → position increment left-to-right
7. list_sessions() — order by position, default no screenshot
8. list_sessions(include_screenshot=True) — base64 populated
9. focus_session() — happy path + KeyError
10. close() — single session vs all sessions
11. pause_session() — captures screenshot + hint format
12. resume_session() — valid session, session_expired path, not-paused error
13. action() — type (realistic typing with jitter), click, navigate, scroll up/down,
    screenshot, evaluate, select_option, press_key
14. action() — unknown action → ValueError
15. default_label_from_url() helper
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from mcp_env_browser.browser import (
    DEFAULT_TYPING_DELAY_MS,
    BrowserExecutor,
    default_label_from_url,
)

# --- Playwright module-level mock ---
# Inject a fake playwright.sync_api module BEFORE BrowserExecutor._ensure_browser()
# lazy-imports it. This way we never touch a real Chromium in CI.


class _FakePage:
    """Stand-in for playwright.sync_api.Page."""

    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self._url = "about:blank"
        self._title = "Blank"

    def goto(self, url: str) -> None:
        self._url = url

    @property
    def url(self) -> str:
        return self._url

    def title(self) -> str:
        return self._title

    def screenshot(self, full_page: bool = False, clip: dict[str, object] | None = None) -> bytes:
        # 1x1 PNG-ish sentinel
        return b"PNGFAKE"

    def bring_to_front(self) -> None:
        return None

    def click(self, selector: str, timeout: int = 5000) -> None:
        return None

    def evaluate(self, js_code: str) -> Any:
        return {"evaluated": js_code[:20]}

    def select_option(self, selector: str, value: str) -> None:
        return None

    def wait_for_url(self, pattern: str, timeout: int = 10000) -> None:
        return None

    class keyboard:
        @staticmethod
        def type(char: str, delay: int = 0) -> None:
            return None

        @staticmethod
        def press(key: str) -> None:
            return None

    class mouse:
        @staticmethod
        def wheel(x: int, y: int) -> None:
            return None

    def locator(self, selector: str) -> Any:
        loc = MagicMock()
        loc.drag_to = MagicMock(return_value=None)
        loc.hover = MagicMock(return_value=None)
        loc.wait_for = MagicMock(return_value=None)
        return loc


class _FakeContext:
    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser
        self._pages: list[_FakePage] = []
        self._closed = False

    def new_page(self) -> _FakePage:
        page = _FakePage(self)
        self._pages.append(page)
        self._browser._pages.append(page)
        return page

    def close(self) -> None:
        self._closed = True

    def new_cdp_session(self, page: _FakePage) -> MagicMock:
        cdp = MagicMock()
        cdp.send = MagicMock(return_value={})
        cdp.on = MagicMock(return_value=None)
        return cdp


class _FakeBrowser:
    def __init__(self, headless: bool = False) -> None:
        self._pages: list[_FakePage] = []
        self._context = _FakeContext(self)
        self._headless = headless
        self._closed = False

    def new_context(self) -> _FakeContext:
        return self._context

    def new_page(self) -> _FakePage:
        # BrowserExecutor uses _browser.new_page() directly (single shared context)
        return self._context.new_page()

    def close(self) -> None:
        self._closed = True


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()

    def start(self) -> _FakePlaywright:
        """Mimic Playwright sync_playwright().start() chain."""
        return self

    def stop(self) -> None:
        return None


class _FakeChromium:
    def __init__(self) -> None:
        self._browsers: list[_FakeBrowser] = []

    def launch(self, headless: bool = False, args: list[str] | None = None) -> _FakeBrowser:
        b = _FakeBrowser(headless=headless)
        self._browsers.append(b)
        return b


def _sync_playwright() -> _FakePlaywright:
    """Replacement for playwright.sync_api.sync_playwright."""
    return _FakePlaywright()


# Module structure mimicking playwright.sync_api
class _FakePlaywrightModule:
    sync_playwright = staticmethod(_sync_playwright)
    Page = _FakePage  # type: ignore[misc]
    Browser = _FakeBrowser  # type: ignore[misc]
    BrowserContext = _FakeContext  # type: ignore[misc]


@pytest.fixture(autouse=True)
def patch_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake playwright.sync_api into sys.modules."""
    fake_pkg = MagicMock()
    fake_pkg.sync_api = _FakePlaywrightModule()
    fake_pkg.sync_api.Page = _FakePage  # ensure attribute exists
    fake_pkg.sync_api.Browser = _FakeBrowser
    fake_pkg.sync_api.BrowserContext = _FakeContext
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_pkg.sync_api)


# --- helper fixtures ---


@pytest.fixture
def fake_license_client() -> MagicMock:
    lc = MagicMock()
    lc.check.return_value = {
        "valid": True,
        "plan": "dev",
        "tabs_used": 0,
        "tabs_quota": 100,
    }
    lc.increment.return_value = {"ok": True, "tabs_used": 1, "tabs_quota_remaining": 99}
    return lc


@pytest.fixture
def fake_vault() -> MagicMock:
    v = MagicMock()
    v.get.return_value = b"alice:hunter2"
    return v


@pytest.fixture
def executor(
    fake_license_client: MagicMock, fake_vault: MagicMock
) -> BrowserExecutor:
    return BrowserExecutor(
        license_client=fake_license_client,
        vault=fake_vault,
        headless=True,
    )


# --- tests ---


class TestBrowserExecutorConstructor:
    def test_init(self, executor: BrowserExecutor) -> None:
        assert executor._headless is True
        assert executor._browser is None
        assert executor._playwright is None
        assert executor._sessions == {}
        assert executor._next_position == 0

    def test_ensure_browser_lazy(
        self, executor: BrowserExecutor, fake_license_client: MagicMock
    ) -> None:
        """First connect() triggers _ensure_browser()."""
        assert executor._browser is None
        executor.connect(
            target="https://example.com", credential_key="test_cred", label="Test"
        )
        assert executor._browser is not None
        assert fake_license_client.check.called
        assert fake_license_client.increment.called


class TestBrowserExecutorConnect:
    def test_connect_happy_path(
        self,
        executor: BrowserExecutor,
        fake_license_client: MagicMock,
        fake_vault: MagicMock,
    ) -> None:
        result = executor.connect(
            target="https://www.tiktok.com/login",
            credential_key="tiktok_user_alice",
            label="TikTok Login",
        )
        assert "session_id" in result
        assert result["label"] == "TikTok Login"
        assert result["position"] == 0
        assert result["page_handle"] == f"page_{result['session_id']}"
        fake_vault.get.assert_called_once_with("tiktok_user_alice")
        fake_license_client.check.assert_called_once()
        fake_license_client.increment.assert_called_once_with(amount=1)
        # session stored
        assert result["session_id"] in executor._sessions

    def test_connect_credential_not_found_raises(
        self, executor: BrowserExecutor, fake_vault: MagicMock
    ) -> None:
        fake_vault.get.return_value = None
        with pytest.raises(ValueError, match="credential not found: missing"):
            executor.connect(
                target="https://example.com",
                credential_key="missing",
                label="X",
            )
        # No license check, no browser launched
        assert executor._browser is None

    def test_connect_license_invalid_raises(
        self, executor: BrowserExecutor, fake_license_client: MagicMock
    ) -> None:
        fake_license_client.check.return_value = {
            "valid": False,
            "error": "invalid api key",
        }
        with pytest.raises(PermissionError, match="license invalid: invalid api key"):
            executor.connect(
                target="https://example.com", credential_key="cred", label="X"
            )
        # increment NOT called
        fake_license_client.increment.assert_not_called()
        assert executor._browser is None

    def test_connect_quota_exceeded_raises(
        self, executor: BrowserExecutor, fake_license_client: MagicMock
    ) -> None:
        fake_license_client.increment.return_value = {
            "ok": False,
            "quota_exceeded": True,
            "detail": {"tabs_used": 100, "tabs_quota": 100},
        }
        with pytest.raises(PermissionError, match="tab quota exceeded"):
            executor.connect(
                target="https://example.com", credential_key="cred", label="X"
            )
        # license.check DID pass (returned valid)
        assert executor._browser is None  # browser never launched

    def test_connect_increment_other_error_raises(
        self, executor: BrowserExecutor, fake_license_client: MagicMock
    ) -> None:
        fake_license_client.increment.return_value = {
            "ok": False,
            "error": "subscription expired",
        }
        with pytest.raises(PermissionError, match="license increment failed"):
            executor.connect(
                target="https://example.com", credential_key="cred", label="X"
            )

    def test_connect_multiple_sessions_increment_position(
        self, executor: BrowserExecutor
    ) -> None:
        s1 = executor.connect(
            target="https://a.example.com", credential_key="c1", label="A"
        )
        s2 = executor.connect(
            target="https://b.example.com", credential_key="c2", label="B"
        )
        s3 = executor.connect(
            target="https://c.example.com", credential_key="c3", label="C"
        )
        assert s1["position"] == 0
        assert s2["position"] == 1
        assert s3["position"] == 2

    def test_connect_default_label_from_url(self, executor: BrowserExecutor) -> None:
        result = executor.connect(
            target="https://www.tiktok.com/login",
            credential_key="cred",
            label=None,
        )
        assert result["label"] == "Tiktok"  # default_label_from_url strips TLD


class TestBrowserExecutorListSessions:
    def test_list_sessions_orders_by_position(self, executor: BrowserExecutor) -> None:
        executor.connect(target="https://a.example.com", credential_key="c", label="A")
        executor.connect(target="https://b.example.com", credential_key="c", label="B")
        executor.connect(target="https://c.example.com", credential_key="c", label="C")
        sessions = executor.list_sessions()
        assert len(sessions) == 3
        assert [s["position"] for s in sessions] == [0, 1, 2]
        assert [s["label"] for s in sessions] == ["A", "B", "C"]
        # No screenshot by default
        for s in sessions:
            assert "last_screenshot_b64" not in s

    def test_list_sessions_include_screenshot(
        self, executor: BrowserExecutor
    ) -> None:
        executor.connect(target="https://a.example.com", credential_key="c", label="A")
        sessions = executor.list_sessions(include_screenshot=True)
        assert len(sessions) == 1
        assert sessions[0]["last_screenshot_b64"] is not None
        # base64-encoded PNGFAKE
        import base64

        decoded = base64.b64decode(sessions[0]["last_screenshot_b64"])
        assert decoded == b"PNGFAKE"

    def test_list_sessions_empty(self, executor: BrowserExecutor) -> None:
        assert executor.list_sessions() == []


class TestBrowserExecutorFocusSession:
    def test_focus_session_ok(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        # Should not raise
        executor.focus_session(s["session_id"])

    def test_focus_session_not_found_raises(self, executor: BrowserExecutor) -> None:
        with pytest.raises(KeyError, match="session not found: missing"):
            executor.focus_session("missing")


class TestBrowserExecutorClose:
    def test_close_specific_session(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.close(s["session_id"])
        assert result == {"ok": True}
        assert s["session_id"] not in executor._sessions

    def test_close_all_sessions(self, executor: BrowserExecutor) -> None:
        executor.connect(target="https://a.example.com", credential_key="c", label="A")
        executor.connect(target="https://b.example.com", credential_key="c", label="B")
        result = executor.close()
        assert result == {"ok": True}
        assert executor._sessions == {}
        assert executor._browser is None
        assert executor._playwright is None


class TestBrowserExecutorPauseResume:
    def test_pause_session_returns_hint_with_label_position(
        self, executor: BrowserExecutor
    ) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="TikTok Login"
        )
        result = executor.pause_session(s["session_id"], reason="captcha")
        assert result["paused"] is True
        assert "screenshot_base64" in result
        assert result["url"] == "https://example.com"
        assert result["label"] == "TikTok Login"
        assert result["position"] == 0
        assert "Tab 'TikTok Login' at position 0" in result["hint"]
        assert "CAPTCHA" in result["hint"]
        # Session marked paused
        sess = executor._sessions[s["session_id"]]
        assert sess["paused"] is True
        assert sess["status"] == "paused"

    def test_pause_unknown_reason_falls_back_to_other(
        self, executor: BrowserExecutor
    ) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.pause_session(s["session_id"], reason="nonexistent_reason")
        assert "Manual intervention required" in result["hint"]

    def test_pause_session_not_found(self, executor: BrowserExecutor) -> None:
        with pytest.raises(KeyError):
            executor.pause_session("missing", reason="captcha")

    def test_resume_after_pause(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        executor.pause_session(s["session_id"], reason="2fa")
        result = executor.resume_session(s["session_id"])
        assert result["resumed"] is True
        assert result["state"] == "active"
        assert result["page_handle"] == f"page_{s['session_id']}"
        # Session unpaused
        assert executor._sessions[s["session_id"]]["paused"] is False

    def test_resume_not_paused_raises(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        with pytest.raises(ValueError, match="not paused"):
            executor.resume_session(s["session_id"])

    def test_resume_session_expired(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        executor.pause_session(s["session_id"], reason="captcha")
        # Now force page.url/page.title to raise on the resume call
        sess = executor._sessions[s["session_id"]]
        page = sess["page"]
        with (
            patch.object(type(page), "url", new_callable=PropertyMock, side_effect=RuntimeError("closed")),
            patch.object(type(page), "title", side_effect=RuntimeError("closed")),
        ):
            result = executor.resume_session(s["session_id"])
        assert result["resumed"] is False
        assert result["state"] == "session_expired"
        assert result["page_handle"] is None


class TestBrowserExecutorAction:
    def test_action_unknown_raises(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        with pytest.raises(ValueError, match="unknown action: bogus"):
            executor.action(s["session_id"], "bogus")

    def test_action_unknown_session_raises(self, executor: BrowserExecutor) -> None:
        with pytest.raises(KeyError):
            executor.action("missing", "click", selector="button")

    def test_action_navigate(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(s["session_id"], "navigate", url="https://other.com")
        assert result is None  # Playwright sync goto returns None

    def test_action_click(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(s["session_id"], "click", selector="button.submit")
        assert result is None

    def test_action_screenshot_returns_base64(
        self, executor: BrowserExecutor
    ) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(s["session_id"], "screenshot")
        assert "base64" in result
        import base64

        assert base64.b64decode(result["base64"]) == b"PNGFAKE"

    def test_action_screenshot_with_clip(
        self, executor: BrowserExecutor
    ) -> None:
        """clip arg passed through to page.screenshot(clip=...) per refactor §10_mcp_server line 268."""
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        page = executor._sessions[s["session_id"]]["page"]
        with patch.object(page, "screenshot", return_value=b"CLIPPED") as mock_shot:
            result = executor.action(
                s["session_id"],
                "screenshot",
                clip={"x": 10, "y": 20, "width": 300, "height": 200},
            )
        # Verify page.screenshot called with clip kwarg
        mock_shot.assert_called_once_with(
            full_page=False,
            clip={"x": 10, "y": 20, "width": 300, "height": 200},
        )
        # Verify result is base64-encoded CLIPPED
        import base64

        assert base64.b64decode(result["base64"]) == b"CLIPPED"

    def test_action_evaluate_returns_value(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(
            s["session_id"], "evaluate", js_code="document.title"
        )
        assert result == {"evaluated": "document.title"}

    def test_action_scroll_down(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(
            s["session_id"], "scroll", direction="down", amount=300
        )
        assert result is None

    def test_action_scroll_up(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(
            s["session_id"], "scroll", direction="up", amount=300
        )
        assert result is None

    def test_action_drag(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(
            s["session_id"],
            "drag",
            from_selector="div.a",
            to_selector="div.b",
        )
        assert result is None

    def test_action_hover(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(s["session_id"], "hover", selector="div.x")
        assert result is None

    def test_action_wait_for_selector(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(s["session_id"], "wait_for_selector", selector="div.x")
        assert result is None

    def test_action_wait_for_navigation(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(s["session_id"], "wait_for_navigation")
        assert result is None

    def test_action_select_option(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(
            s["session_id"], "select_option", selector="select#x", value="opt1"
        )
        assert result is None

    def test_action_press_key(self, executor: BrowserExecutor) -> None:
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        result = executor.action(s["session_id"], "press_key", key="Enter")
        assert result is None

    def test_action_type_realistic_typing(
        self, executor: BrowserExecutor
    ) -> None:
        """Type action with jitter — calls page.keyboard.type per char."""
        s = executor.connect(
            target="https://example.com", credential_key="c", label="X"
        )
        # Spy on keyboard.type
        page = executor._sessions[s["session_id"]]["page"]
        with patch.object(page.keyboard, "type") as mock_type:
            executor.action(
                s["session_id"], "type", text="hi", delay_ms=DEFAULT_TYPING_DELAY_MS
            )
            # 2 chars → 2 calls
            assert mock_type.call_count == 2
            # Each call has a delay in [30, 70] ms (50±20)
            for call in mock_type.call_args_list:
                assert 30 <= call.kwargs["delay"] <= 70


class TestDefaultLabelFromUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.tiktok.com/login", "Tiktok"),
            ("https://github.com", "Github"),
            ("https://accounts.google.com/signin", "Accounts"),
            ("https://example.com", "Example"),
            ("https://localhost:9876", "Localhost:9876"),
            # urlparse("not-a-url").netloc returns "" → function returns "Unnamed"
            ("not-a-url", "Unnamed"),
            ("", "Unnamed"),
        ],
    )
    def test_label_extraction(self, url: str, expected: str) -> None:
        assert default_label_from_url(url) == expected
