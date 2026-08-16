"""Unit tests untuk CDPHelpers (Phase 6).

Per refactor/30_client_arch.md §cdp.py line 219-273.

Strategy: mock Playwright Page + CDP client (MagicMock). We don't exercise
real Chromium DOM/network/console events — the CDP helpers just translate
between Playwright's CDP API and Python dicts.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from mcp_env_browser.browser.cdp import CDPHelpers


class _FakeContext:
    def __init__(self) -> None:
        self._cdp = MagicMock()

    def new_cdp_session(self, page: Any) -> MagicMock:
        return self._cdp


class _FakePage:
    def __init__(self) -> None:
        self.context = _FakeContext()


class _FakePlaywrightModule:
    Page = _FakePage  # type: ignore[misc]


@pytest.fixture(autouse=True)
def patch_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    """CDPHelpers type-hints Page but doesn't import it at runtime.
    Patch to avoid mypy noise + keep test isolation."""
    fake_pkg = MagicMock()
    fake_pkg.sync_api = _FakePlaywrightModule()
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_pkg.sync_api)


@pytest.fixture
def fake_page() -> _FakePage:
    return _FakePage()


@pytest.fixture
def cdp(fake_page: _FakePage) -> CDPHelpers:
    return CDPHelpers(fake_page)  # type: ignore[arg-type]


class TestConsoleCapture:
    def test_enable_console_calls_domain(self, cdp: CDPHelpers) -> None:
        cdp.enable_console()
        cdp._page.context._cdp.send.assert_called_once_with("Console.enable")
        cdp._page.context._cdp.on.assert_called_once()
        event_name = cdp._page.context._cdp.on.call_args.args[0]
        assert event_name == "Console.messageAdded"

    def test_get_console_log_empty(self, cdp: CDPHelpers) -> None:
        cdp.enable_console()
        assert cdp.get_console_log() == []

    def test_console_message_event_appends(self, cdp: CDPHelpers) -> None:
        cdp.enable_console()
        # Grab the registered callback and invoke it manually
        callback = cdp._page.context._cdp.on.call_args.args[1]
        callback(
            {
                "message": {
                    "level": "error",
                    "text": "Failed to load",
                    "url": "https://example.com/script.js",
                }
            }
        )
        log = cdp.get_console_log()
        assert len(log) == 1
        assert log[0]["level"] == "error"
        assert log[0]["text"] == "Failed to load"

    def test_console_log_filter_by_level(self, cdp: CDPHelpers) -> None:
        cdp.enable_console()
        callback = cdp._page.context._cdp.on.call_args.args[1]
        callback({"message": {"level": "error", "text": "err1"}})
        callback({"message": {"level": "warn", "text": "warn1"}})
        callback({"message": {"level": "error", "text": "err2"}})
        errors = cdp.get_console_log(level="error")
        assert len(errors) == 2
        assert all(m["level"] == "error" for m in errors)


class TestNetworkCapture:
    def test_enable_network_calls_domain(self, cdp: CDPHelpers) -> None:
        cdp.enable_network()
        send_calls = cdp._page.context._cdp.send.call_args_list
        assert any(c.args[0] == "Network.enable" for c in send_calls)
        on_calls = cdp._page.context._cdp.on.call_args_list
        events = {c.args[0] for c in on_calls}
        assert "Network.requestWillBeSent" in events
        assert "Network.responseReceived" in events

    def test_request_response_pairing(self, cdp: CDPHelpers) -> None:
        cdp.enable_network()
        # Grab the request handler
        req_handler = next(
            c.args[1]
            for c in cdp._page.context._cdp.on.call_args_list
            if c.args[0] == "Network.requestWillBeSent"
        )
        resp_handler = next(
            c.args[1]
            for c in cdp._page.context._cdp.on.call_args_list
            if c.args[0] == "Network.responseReceived"
        )
        req_handler(
            {
                "requestId": "r1",
                "request": {"url": "https://api.tiktok.com/foo", "method": "POST"},
            }
        )
        resp_handler({"requestId": "r1", "response": {"status": 200}})
        log = cdp.get_network_log()
        assert len(log) == 1
        assert log[0]["url"] == "https://api.tiktok.com/foo"
        assert log[0]["method"] == "POST"
        assert log[0]["status"] == 200
        assert log[0]["duration_ms"] is not None
        assert log[0]["duration_ms"] >= 0

    def test_network_log_filter(self, cdp: CDPHelpers) -> None:
        cdp.enable_network()
        req_handler = next(
            c.args[1]
            for c in cdp._page.context._cdp.on.call_args_list
            if c.args[0] == "Network.requestWillBeSent"
        )
        req_handler(
            {
                "requestId": "r1",
                "request": {"url": "https://api.tiktok.com/foo", "method": "GET"},
            }
        )
        req_handler(
            {
                "requestId": "r2",
                "request": {"url": "https://other.com/bar", "method": "GET"},
            }
        )
        tiktok = cdp.get_network_log(filter_text="tiktok")
        assert len(tiktok) == 1
        assert tiktok[0]["url"].endswith("/foo")


class TestInspectElement:
    def test_inspect_found(self, cdp: CDPHelpers) -> None:
        # Configure CDP client responses
        cdp._page.context._cdp.send.side_effect = [
            # DOM.getDocument
            {"root": {"nodeId": 1}},
            # DOM.querySelector
            {"nodeId": 42},
            # DOM.describeNode
            {
                "node": {
                    "nodeName": "DIV",
                    "attributes": ["class", "submit", "id", "x1"],
                    "outerHTML": '<div class="submit" id="x1">hi</div>',
                }
            },
            # CSS.getComputedStyle
            {
                "computedStyle": [
                    {"name": "color", "value": "rgb(0,0,0)"},
                    {"name": "display", "value": "block"},
                    # Filter: not in whitelist
                    {"name": "background-image", "value": "url(...)"},
                ]
            },
            # DOM.getChildNodeCount
            {"childNodeCount": 3},
        ]
        result = cdp.inspect_element(".submit")
        assert result["found"] is True
        assert result["tag"] == "div"
        assert result["attrs"] == {"class": "submit", "id": "x1"}
        assert result["children_count"] == 3
        assert result["computed_style"]["color"] == "rgb(0,0,0)"
        assert result["computed_style"]["display"] == "block"
        # Whitelist filter
        assert "background-image" not in result["computed_style"]

    def test_inspect_not_found(self, cdp: CDPHelpers) -> None:
        cdp._page.context._cdp.send.side_effect = [
            {"root": {"nodeId": 1}},
            {"nodeId": 0},  # not found
        ]
        result = cdp.inspect_element(".missing")
        assert result["found"] is False
        assert "not found" in result["error"]

    def test_inspect_truncates_long_html(self, cdp: CDPHelpers) -> None:
        long_html = "<div>" + ("x" * 600) + "</div>"
        cdp._page.context._cdp.send.side_effect = [
            {"root": {"nodeId": 1}},
            {"nodeId": 42},
            {"node": {"nodeName": "DIV", "attributes": [], "outerHTML": long_html}},
            {"computedStyle": []},
            {"childNodeCount": 0},
        ]
        result = cdp.inspect_element(".x")
        assert result["outer_html_truncated"].endswith("...")
        assert len(result["outer_html_truncated"]) <= 504  # 500 + "..."
