"""Unit tests untuk MCP Server (Phase 6).

Per refactor/10_mcp_server.md (full spec).

Strategy:
1. Build Server via `build_server(vault, browser_executor)` factory.
2. Pull registered handlers from `server.request_handlers[RequestType]`.
3. Invoke them directly with synthetic request objects — bypasses stdio.

Tests cover:
- list_tools returns 13 tools
- list_prompts returns 3 prompts
- get_prompt returns PromptMessage list for all 3 prompts
- get_prompt raises ValueError for missing required argument
- get_prompt raises ValueError for unknown prompt
- call_tool dispatch all 13 tools via _dispatch + asyncio.to_thread
- call_tool returns isError=True for unknown tool
- Security: smart_get_credential_meta NEVER returns password/value/token
- _set_credential auto-encrypts JSON value
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp import types as mcp_types

from mcp_env_browser.mcp_server import (
    _DEBUG_PROMPT_TEMPLATE,
    _HUMAN_INTERVENTION_TEMPLATE,
    _OAUTH_PROMPT_TEMPLATE,
    _TOOL_REGISTRY,
)

# --- Playwright + Page mocks (so CDPHelpers can type-hint without import error) ---


class _FakeContext:
    def __init__(self) -> None:
        # Default CDP send returns JSON-serializable empty dict
        cdp = MagicMock()
        cdp.send = MagicMock(
            side_effect=[
                # DOM.getDocument
                {"root": {"nodeId": 1}},
                # DOM.querySelector → not found (returns nodeId 0)
                {"nodeId": 0},
            ]
        )
        cdp.on = MagicMock(return_value=None)
        self._cdp = cdp

    def new_cdp_session(self, page: Any) -> MagicMock:
        return self._cdp


class _FakePage:
    def __init__(self) -> None:
        self.context = _FakeContext()
        self._url = "about:blank"

    @property
    def url(self) -> str:
        return self._url


class _FakePlaywrightModule:
    Page = _FakePage  # type: ignore[misc]


@pytest.fixture(autouse=True)
def patch_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pkg = MagicMock()
    fake_pkg.sync_api = _FakePlaywrightModule()
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_pkg.sync_api)


# --- fixtures ---


@pytest.fixture
def fake_vault() -> MagicMock:
    v = MagicMock()
    v.list_keys.return_value = [
        {"key": "tiktok_user_alice", "type": "username_password", "summary": "alice@example.com"},
        {"key": "github_oauth_yaden", "type": "oauth_token", "summary": "***exp:2026-12-01"},
    ]
    # vault.get returns bytes containing JSON for username_password
    v.get.return_value = json.dumps(
        {"username": "alice@example.com", "password": "hunter2"}
    ).encode("utf-8")
    return v


@pytest.fixture
def fake_license_client() -> MagicMock:
    lc = MagicMock()
    lc.check.return_value = {"valid": True}
    lc.increment.return_value = {"ok": True}
    return lc


@pytest.fixture
def fake_browser_executor() -> MagicMock:
    """Browser executor with MagicMock methods that return sensible defaults."""
    be = MagicMock()
    be.connect.return_value = {
        "session_id": "abc123",
        "label": "Test",
        "position": 0,
        "page_handle": "page_abc123",
    }
    be.list_sessions.return_value = [
        {"session_id": "abc", "label": "Test", "position": 0, "url": "https://x", "status": "active", "age_seconds": 5}
    ]
    be.close.return_value = {"ok": True}
    be.action.return_value = {"ok": True}
    be.pause_session.return_value = {
        "paused": True,
        "screenshot_base64": "ZmFrZQ==",
        "url": "https://example.com",
        "hint": "Please solve the CAPTCHA in Tab 'Test' at position 0",
    }
    be.resume_session.return_value = {
        "ok": True,
        "resumed": True,
        "page_handle": "page_abc",
        "state": "active",
        "url": "https://example.com",
    }
    be.get_session.return_value = {"page": _FakePage(), "label": "X", "position": 0}
    return be


@pytest.fixture
def server(fake_vault: MagicMock, fake_browser_executor: MagicMock) -> Any:
    """Test server: bypass FastMCP runtime via _build_test_handlers.

    Returns a dict-like object with `request_handlers[RequestType]` keys
    populated by raw async handler functions (so tests can dispatch directly).
    """
    from mcp_env_browser.mcp_server import _build_test_handlers

    class _TestServer:
        def __init__(self, handlers: dict[type[Any], Any]) -> None:
            self.request_handlers = handlers

    return _TestServer(
        _build_test_handlers(vault=fake_vault, browser_executor=fake_browser_executor)
    )


def _invoke(handler: Any, request: Any) -> Any:
    """Invoke MCP handler directly (bypass stdio)."""
    import asyncio

    return asyncio.run(handler(request))


def _make_call_tool_request(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Build a CallToolRequest with given tool name + args."""
    return mcp_types.CallToolRequest(
        params=mcp_types.CallToolRequestParams(name=name, arguments=arguments or {})
    )


def _make_get_prompt_request(name: str, arguments: dict[str, Any] | None = None) -> Any:
    return mcp_types.GetPromptRequest(
        params=mcp_types.GetPromptRequestParams(name=name, arguments=arguments or {})
    )


# ============================================================================
# Tests
# ============================================================================


class TestListTools:
    def test_returns_13_tools(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.ListToolsRequest]
        result = _invoke(handler, mcp_types.ListToolsRequest())
        # ServerResult wrapper
        inner = result.root if hasattr(result, "root") else result
        tools = inner.tools if hasattr(inner, "tools") else inner
        assert len(tools) == 13
        names = {t.name for t in tools}
        assert "smart_connect_browser" in names
        assert "smart_session_pause" in names
        assert "smart_browser_action" in names
        assert "smart_browser_inspect" in names

    def test_tool_registry_has_13(self) -> None:
        assert len(_TOOL_REGISTRY) == 13

    def test_each_tool_has_input_schema(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.ListToolsRequest]
        result = _invoke(handler, mcp_types.ListToolsRequest())
        inner = result.root if hasattr(result, "root") else result
        tools = inner.tools if hasattr(inner, "tools") else inner
        for tool in tools:
            assert tool.inputSchema.get("type") == "object"
            assert "properties" in tool.inputSchema

    def test_browser_action_schema_has_clip(self, server: Any) -> None:
        """clip arg declared in smart_browser_action inputSchema per spec §6.4."""
        handler = server.request_handlers[mcp_types.ListToolsRequest]
        result = _invoke(handler, mcp_types.ListToolsRequest())
        inner = result.root if hasattr(result, "root") else result
        tools = inner.tools if hasattr(inner, "tools") else inner
        browser_action = next(t for t in tools if t.name == "smart_browser_action")
        props = browser_action.inputSchema["properties"]
        assert "clip" in props
        # clip is object with x/y/width/height
        assert props["clip"]["type"] == "object"
        clip_props = props["clip"]["properties"]
        assert set(clip_props.keys()) == {"x", "y", "width", "height"}
        assert props["clip"]["required"] == ["x", "y", "width", "height"]


class TestListPrompts:
    def test_returns_3_prompts(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.ListPromptsRequest]
        result = _invoke(handler, mcp_types.ListPromptsRequest())
        inner = result.root if hasattr(result, "root") else result
        prompts = inner.prompts if hasattr(inner, "prompts") else inner
        assert len(prompts) == 3
        names = {p.name for p in prompts}
        assert names == {
            "oauth_confirmation_flow",
            "browser_debug_workflow",
            "human_intervention_workflow",
        }

    def test_oauth_prompt_template_content(self) -> None:
        assert "oauth_required" in _OAUTH_PROMPT_TEMPLATE
        assert "smart_connect_browser" in _OAUTH_PROMPT_TEMPLATE
        assert "JANGAN auto-input password" in _OAUTH_PROMPT_TEMPLATE

    def test_debug_prompt_requires_symptom(self) -> None:
        assert "Console" in _DEBUG_PROMPT_TEMPLATE
        assert "Network" in _DEBUG_PROMPT_TEMPLATE
        assert "DOM" in _DEBUG_PROMPT_TEMPLATE

    def test_human_intervention_prompt_includes_pause_resume(self) -> None:
        assert "smart_session_pause" in _HUMAN_INTERVENTION_TEMPLATE
        assert "smart_session_resume" in _HUMAN_INTERVENTION_TEMPLATE
        assert "CAPTCHA" in _HUMAN_INTERVENTION_TEMPLATE


class TestGetPrompt:
    def test_oauth_confirmation_flow(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request("oauth_confirmation_flow", {"service": "tiktok"})
        result = _invoke(handler, req)
        inner = result.root if hasattr(result, "root") else result
        messages = inner.messages if hasattr(inner, "messages") else inner
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert "tiktok" in messages[0].content.text
        assert messages[1].role == "assistant"
        assert "JANGAN auto-input password" in messages[1].content.text

    def test_oauth_missing_service_raises(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request("oauth_confirmation_flow", {})
        with pytest.raises(ValueError, match="requires 'service'"):
            _invoke(handler, req)

    def test_oauth_prompt_with_scopes(self, server: Any) -> None:
        """scopes arg (optional) — incorporated into prompt per spec §6.4.1."""
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request(
            "oauth_confirmation_flow",
            {"service": "github", "scopes": "user:read,user:write"},
        )
        result = _invoke(handler, req)
        inner = result.root if hasattr(result, "root") else result
        messages = inner.messages if hasattr(inner, "messages") else inner
        assert "user:read,user:write" in messages[1].content.text
        assert "Scopes needed" in messages[1].content.text

    def test_oauth_prompt_without_scopes_still_works(self, server: Any) -> None:
        """scopes arg optional — without it, default fallback message appears."""
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request("oauth_confirmation_flow", {"service": "tiktok"})
        result = _invoke(handler, req)
        inner = result.root if hasattr(result, "root") else result
        messages = inner.messages if hasattr(inner, "messages") else inner
        assert "Scopes: detect dari OAuth provider" in messages[1].content.text

    def test_oauth_prompt_scopes_in_list(self, server: Any) -> None:
        """list_prompts declares scopes as optional arg."""
        handler = server.request_handlers[mcp_types.ListPromptsRequest]
        result = _invoke(handler, mcp_types.ListPromptsRequest())
        inner = result.root if hasattr(result, "root") else result
        prompts = inner.prompts if hasattr(inner, "prompts") else inner
        oauth = next(p for p in prompts if p.name == "oauth_confirmation_flow")
        arg_names = {a.name for a in oauth.arguments}
        assert "service" in arg_names
        assert "scopes" in arg_names

    def test_browser_debug_workflow(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request(
            "browser_debug_workflow",
            {"symptom": "click did nothing", "service": "tiktok.com"},
        )
        result = _invoke(handler, req)
        inner = result.root if hasattr(result, "root") else result
        messages = inner.messages if hasattr(inner, "messages") else inner
        assert len(messages) == 2
        assert "click did nothing" in messages[0].content.text
        assert "tiktok.com" in messages[0].content.text
        assert "Correlate" in messages[1].content.text

    def test_browser_debug_missing_symptom_raises(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request("browser_debug_workflow", {})
        with pytest.raises(ValueError, match="requires 'symptom'"):
            _invoke(handler, req)

    def test_human_intervention_workflow(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request(
            "human_intervention_workflow", {"challenge_type": "captcha"}
        )
        result = _invoke(handler, req)
        inner = result.root if hasattr(result, "root") else result
        messages = inner.messages if hasattr(inner, "messages") else inner
        assert len(messages) == 2
        assert "captcha" in messages[0].content.text
        assert "smart_session_pause" in messages[1].content.text

    def test_human_intervention_with_context(self, server: Any) -> None:
        """context arg (optional) — incorporated into User message per spec §6.4.1."""
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request(
            "human_intervention_workflow",
            {
                "challenge_type": "captcha",
                "context": "submitting tax form, halaman konfirmasi muncul",
            },
        )
        result = _invoke(handler, req)
        inner = result.root if hasattr(result, "root") else result
        messages = inner.messages if hasattr(inner, "messages") else inner
        assert "submitting tax form" in messages[0].content.text
        assert "captcha" in messages[0].content.text

    def test_human_intervention_context_in_list(self, server: Any) -> None:
        """list_prompts declares context as optional arg."""
        handler = server.request_handlers[mcp_types.ListPromptsRequest]
        result = _invoke(handler, mcp_types.ListPromptsRequest())
        inner = result.root if hasattr(result, "root") else result
        prompts = inner.prompts if hasattr(inner, "prompts") else inner
        hi = next(p for p in prompts if p.name == "human_intervention_workflow")
        arg_names = {a.name for a in hi.arguments}
        assert "challenge_type" in arg_names
        assert "context" in arg_names

    def test_human_intervention_missing_challenge_raises(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request("human_intervention_workflow", {})
        with pytest.raises(ValueError, match="requires 'challenge_type'"):
            _invoke(handler, req)

    def test_unknown_prompt_raises(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.GetPromptRequest]
        req = _make_get_prompt_request("nonexistent_prompt", {})
        with pytest.raises(ValueError, match="unknown prompt"):
            _invoke(handler, req)


class TestBuildServer:
    """Tests for build_server() factory function (FastMCP/MCPServer wrapper)."""

    def test_build_server_returns_server_instance(
        self, fake_vault: MagicMock, fake_browser_executor: MagicMock
    ) -> None:
        """build_server() should return a non-None server object."""
        from mcp_env_browser.mcp_server import build_server
        server = build_server(vault=fake_vault, browser_executor=fake_browser_executor)
        assert server is not None

    def test_build_server_handles_missing_mcp_2x(
        self, fake_vault: MagicMock, fake_browser_executor: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_server() should handle ImportError gracefully if mcp 2.x unavailable."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "mcp.server.mcpserver":
                raise ImportError("simulated mcp 2.x not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        # Should not raise if mcp 1.x works (FastMCP)
        from mcp_env_browser.mcp_server import build_server
        try:
            server = build_server(vault=fake_vault, browser_executor=fake_browser_executor)
            # Either FastMCP found or RuntimeError raised (if both missing)
            assert server is not None
        except RuntimeError as e:
            # Acceptable if neither mcp 1.x nor 2.x available
            assert "mcp package not importable" in str(e)


class TestCallToolCredential:
    def test_smart_list_credentials(
        self, server: Any, fake_vault: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request("smart_list_credentials", {"filter": "tiktok"})
        result = _invoke(handler, req)
        fake_vault.list_keys.assert_called_once_with("tiktok")
        # Response is ServerResult(CallToolResult(content=[TextContent(text=json.dumps(...))]))
        text = _extract_text(result)
        data = json.loads(text)
        assert isinstance(data, list)
        assert data[0]["key"] == "tiktok_user_alice"

    def test_smart_get_credential_meta_returns_no_password(
        self, server: Any
    ) -> None:
        """SECURITY: never return plaintext password."""
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_get_credential_meta", {"key": "tiktok_user_alice"}
        )
        result = _invoke(handler, req)
        text = _extract_text(result)
        data = json.loads(text)
        assert data["key"] == "tiktok_user_alice"
        assert data["type"] == "username_password"
        # Username is metadata (OK)
        assert data["username"] == "alice@example.com"
        # Password is NEVER returned
        assert "password" not in data
        assert "value" not in data
        assert "hunter2" not in text

    def test_smart_get_credential_meta_not_found(
        self, server: Any, fake_vault: MagicMock
    ) -> None:
        fake_vault.list_keys.return_value = []
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_get_credential_meta", {"key": "missing"}
        )
        result = _invoke(handler, req)
        # isError=True
        assert _is_error(result)

    def test_smart_set_credential_auto_encrypts(
        self, server: Any, fake_vault: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_set_credential",
            {
                "key": "new_cred",
                "type": "api_key",
                "value": {"key": "sk-abc"},
            },
        )
        _invoke(handler, req)
        # vault.set called with (key, value_bytes, attributes=...)
        fake_vault.set.assert_called_once()
        call = fake_vault.set.call_args
        assert call.args[0] == "new_cred"
        assert isinstance(call.args[1], bytes)
        decoded = json.loads(call.args[1].decode("utf-8"))
        assert decoded == {"key": "sk-abc"}
        assert call.kwargs == {"attributes": {"type": "api_key", "app": "mcp-env-browser"}}

    def test_smart_delete_credential(
        self, server: Any, fake_vault: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request("smart_delete_credential", {"key": "old_cred"})
        _invoke(handler, req)
        fake_vault.delete.assert_called_once_with("old_cred")


class TestCallToolBrowser:
    def test_smart_connect_browser(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_connect_browser",
            {"target": "https://x.com", "credential_key": "ck", "label": "Test"},
        )
        result = _invoke(handler, req)
        fake_browser_executor.connect.assert_called_once_with(
            "https://x.com", "ck", "Test"
        )
        text = _extract_text(result)
        data = json.loads(text)
        assert data["session_id"] == "abc123"

    def test_smart_list_sessions_no_screenshot(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_list_sessions", {"include_screenshot": False}
        )
        _invoke(handler, req)
        fake_browser_executor.list_sessions.assert_called_once_with(False)

    def test_smart_close_browser_with_session(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request("smart_close_browser", {"session_id": "abc"})
        _invoke(handler, req)
        fake_browser_executor.close.assert_called_once_with("abc")

    def test_smart_close_browser_all(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request("smart_close_browser", {})
        _invoke(handler, req)
        fake_browser_executor.close.assert_called_once_with(None)

    def test_smart_browser_action_dispatches_kwargs(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_browser_action",
            {
                "session_id": "abc",
                "action": "navigate",
                "url": "https://target.com",
            },
        )
        _invoke(handler, req)
        # action() called with session_id, action, **rest_kwargs (url extracted)
        fake_browser_executor.action.assert_called_once()
        args = fake_browser_executor.action.call_args
        assert args.args[0] == "abc"  # session_id positional
        assert args.args[1] == "navigate"  # action positional
        assert args.kwargs == {"url": "https://target.com"}

    def test_smart_session_pause(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_session_pause", {"session_id": "abc", "reason": "captcha"}
        )
        result = _invoke(handler, req)
        fake_browser_executor.pause_session.assert_called_once_with("abc", "captcha")
        text = _extract_text(result)
        data = json.loads(text)
        assert data["paused"] is True

    def test_smart_session_resume(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request("smart_session_resume", {"session_id": "abc"})
        result = _invoke(handler, req)
        fake_browser_executor.resume_session.assert_called_once_with("abc")
        text = _extract_text(result)
        data = json.loads(text)
        assert data["resumed"] is True


class TestCallToolCDP:
    def test_smart_browser_console_log(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_browser_console_log", {"session_id": "abc", "type": "error"}
        )
        result = _invoke(handler, req)
        # Verify response shape (CDPHelpers.enable_console() called via real class)
        text = _extract_text(result)
        data = json.loads(text)
        assert "messages" in data

    def test_smart_browser_network_log(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_browser_network_log", {"session_id": "abc", "filter": "tiktok"}
        )
        result = _invoke(handler, req)
        text = _extract_text(result)
        data = json.loads(text)
        assert "requests" in data

    def test_smart_browser_inspect(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_browser_inspect", {"session_id": "abc", "selector": ".btn"}
        )
        result = _invoke(handler, req)
        text = _extract_text(result)
        data = json.loads(text)
        # Default CDP mock returns DOM.getDocument + DOM.querySelector with nodeId=0
        # → CDPHelpers.inspect_element returns found=False
        assert data.get("found") is False
        assert "not found" in data.get("error", "")

    def test_cdp_session_not_found(
        self, server: Any, fake_browser_executor: MagicMock
    ) -> None:
        fake_browser_executor.get_session.return_value = None
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request(
            "smart_browser_console_log", {"session_id": "missing"}
        )
        result = _invoke(handler, req)
        assert _is_error(result)


class TestCallToolErrorHandling:
    def test_unknown_tool_returns_error(self, server: Any) -> None:
        handler = server.request_handlers[mcp_types.CallToolRequest]
        req = _make_call_tool_request("smart_nonexistent", {})
        result = _invoke(handler, req)
        assert _is_error(result)


# ============================================================================
# Helpers
# ============================================================================


def _extract_text(result: Any) -> str:
    """Extract TextContent text from a CallToolResult (or ServerResult wrapper)."""
    # MCP returns ServerResult(CallToolResult(...)) — unwrap
    if hasattr(result, "root"):
        result = result.root
    content = result.content
    # content is list[TextContent] — take first
    for block in content:
        if block.type == "text":
            return block.text
    raise AssertionError(f"no text content in: {result!r}")


def _is_error(result: Any) -> bool:
    if hasattr(result, "root"):
        result = result.root
    return bool(result.isError)
