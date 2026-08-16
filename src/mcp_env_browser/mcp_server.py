"""MCP stdio server — exposes 13 tools + 3 prompts to agent.

Per refactor/10_mcp_server.md (full spec) + refactor/30_client_arch.md.

Phase 6 implementation. Wired components:
- VaultBackend (Phase 3) — credential storage via libsecret/encrypted_json
- LicenseClient (Phase 4) — license check + tab counter (used by BrowserExecutor)
- BrowserExecutor (Phase 5) — Playwright wrapper, used for browser tools

Async pattern (per 10_mcp_server.md §"Async Pattern" line 366-382):
- All MCP handlers are `async def`.
- Sync Playwright methods are wrapped via `asyncio.to_thread()`.

Security (per 10_mcp_server.md §smart_get_credential_meta line 102 + spec §1):
- NEVER return plaintext password/value/token in TextContent.
- Only metadata (key, type, username, created_at).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast

from mcp.types import (
    CallToolResult,
    GetPromptResult,
    ListPromptsResult,
    ListToolsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
)

if TYPE_CHECKING:
    from mcp_env_browser.browser import BrowserExecutor
    from mcp_env_browser.license import LicenseClient
    from mcp_env_browser.vault import VaultBackend

logger = logging.getLogger(__name__)


# ============================================================================
# Tool input schemas (JSON Schema fragments for Tool.inputSchema)
# ============================================================================


_LIST_CREDENTIALS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "filter": {"type": "string", "description": "substring match against key/type"},
    },
    "additionalProperties": False,
}

_GET_CRED_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "credential key in vault"},
    },
    "required": ["key"],
    "additionalProperties": False,
}

_SET_CREDENTIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "type": {
            "type": "string",
            "enum": ["username_password", "api_key", "oauth_token", "ssh_key"],
        },
        "value": {
            "type": "object",
            "description": "credential payload (e.g. {username, password} for username_password)",
        },
    },
    "required": ["key", "type", "value"],
    "additionalProperties": False,
}

_DELETE_CREDENTIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"key": {"type": "string"}},
    "required": ["key"],
    "additionalProperties": False,
}

_CONNECT_BROWSER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "description": "URL to navigate"},
        "credential_key": {"type": "string"},
        "label": {
            "type": "string",
            "description": "human-readable label (optional, default = domain)",
        },
    },
    "required": ["target", "credential_key"],
    "additionalProperties": False,
}

_LIST_SESSIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "include_screenshot": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
}

_CLOSE_BROWSER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "session to close (omit to close all)",
        },
    },
    "additionalProperties": False,
}

_BROWSER_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "action": {
            "type": "string",
            "enum": [
                "navigate",
                "click",
                "type",
                "scroll",
                "drag",
                "hover",
                "screenshot",
                "wait_for_selector",
                "wait_for_navigation",
                "evaluate",
                "select_option",
                "press_key",
            ],
        },
        # Optional action-specific kwargs
        "url": {"type": "string"},
        "selector": {"type": "string"},
        "text": {"type": "string"},
        "delay_ms": {"type": "integer", "default": 50},
        "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
        "amount": {"type": "integer"},
        "from_selector": {"type": "string"},
        "to_selector": {"type": "string"},
        "full_page": {"type": "boolean", "default": False},
        "clip": {
            "type": "object",
            "description": "Crop region for screenshot: {x, y, width, height} in CSS pixels",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "width": {"type": "number"},
                "height": {"type": "number"},
            },
            "required": ["x", "y", "width", "height"],
            "additionalProperties": False,
        },
        "timeout_ms": {"type": "integer"},
        "js_code": {"type": "string"},
        "value": {"type": "string"},
        "key": {"type": "string"},
    },
    "required": ["session_id", "action"],
    "additionalProperties": False,
}

_CONSOLE_LOG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "type": {"type": "string", "enum": ["log", "warn", "error", "info", "debug"]},
    },
    "required": ["session_id"],
    "additionalProperties": False,
}

_NETWORK_LOG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "filter": {"type": "string", "description": "substring match against URL"},
    },
    "required": ["session_id"],
    "additionalProperties": False,
}

_INSPECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "selector": {"type": "string"},
    },
    "required": ["session_id", "selector"],
    "additionalProperties": False,
}

_PAUSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "reason": {
            "type": "string",
            "enum": [
                "captcha",
                "2fa",
                "purchase_confirmation",
                "tos_accept",
                "manual_review",
                "other",
            ],
        },
    },
    "required": ["session_id", "reason"],
    "additionalProperties": False,
}

_RESUME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"session_id": {"type": "string"}},
    "required": ["session_id"],
    "additionalProperties": False,
}


# Tool name → (inputSchema, short_description)
_TOOL_REGISTRY: dict[str, tuple[dict[str, Any], str]] = {
    "smart_list_credentials": (
        _LIST_CREDENTIALS_SCHEMA,
        "List credential keys (metadata only, NO plaintext).",
    ),
    "smart_get_credential_meta": (
        _GET_CRED_META_SCHEMA,
        "Get credential metadata (key, type, username). No password.",
    ),
    "smart_set_credential": (
        _SET_CREDENTIAL_SCHEMA,
        "Save credential to vault (auto-encrypt via libsecret).",
    ),
    "smart_delete_credential": (
        _DELETE_CREDENTIAL_SCHEMA,
        "Delete credential from vault.",
    ),
    "smart_connect_browser": (
        _CONNECT_BROWSER_SCHEMA,
        "Open browser session, login via credential_key (K1 per-tab counter).",
    ),
    "smart_list_sessions": (
        _LIST_SESSIONS_SCHEMA,
        "List active browser sessions (ordered by position).",
    ),
    "smart_close_browser": (
        _CLOSE_BROWSER_SCHEMA,
        "Close one session (session_id) or all sessions.",
    ),
    "smart_browser_action": (
        _BROWSER_ACTION_SCHEMA,
        "Dispatch browser action (navigate|click|type|scroll|drag|hover|screenshot|...).",
    ),
    "smart_browser_console_log": (
        _CONSOLE_LOG_SCHEMA,
        "Get browser console messages (CDP Console.messageAdded).",
    ),
    "smart_browser_network_log": (
        _NETWORK_LOG_SCHEMA,
        "Get browser network requests (CDP Network.requestWillBeSent).",
    ),
    "smart_browser_inspect": (
        _INSPECT_SCHEMA,
        "Inspect DOM element via CDP (tag, attrs, computed_style, children).",
    ),
    "smart_session_pause": (
        _PAUSE_SCHEMA,
        "Pause session for user intervention (CAPTCHA/2FA/manual). Returns screenshot.",
    ),
    "smart_session_resume": (
        _RESUME_SCHEMA,
        "Resume paused session. Verifies session is still alive.",
    ),
}


# ============================================================================
# Prompt templates (per refactor/10_mcp_server.md §"MCP Prompts")
# ============================================================================

_OAUTH_PROMPT_TEMPLATE = """\
Pattern berikut untuk handle OAuth re-authentication flow:

1. Detect: cek response tool sebelumnya untuk error code "oauth_required"
2. Open auth URL: panggil smart_connect_browser dengan auth_url={auth_url}
   (URL construction hardcoded per service, lihat knowledge.md §OAuth URLs)
{scopes_line}3. Inform user: kasih instruksi di response text ke user:
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

_DEBUG_PROMPT_TEMPLATE = """\
Pattern investigation 4 langkah:

1. Console: panggil smart_browser_console_log(session_id, type="error")
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

_HUMAN_INTERVENTION_TEMPLATE = """\
Pattern untuk user-replacement saat agent stuck di challenge yang butuh input manusia:

1. Detect challenge type — pilih berdasarkan symptom yang agent alami:
   - "captcha" — visual challenge (reCAPTCHA, hCaptcha, image puzzle)
   - "2fa" — two-factor OTP (TOTP/SMS/email code)
   - "purchase_confirmation" — konfirmasi purchase / payment
   - "tos_accept" — Terms of Service / privacy policy
   - "manual_review" — keputusan sulit yang butuh judgement user
   - "other" — challenge tidak masuk kategori di atas

2. Pause session:
   - panggil smart_session_pause(session_id, reason="<challenge_type>")
   - response berisi: screenshot_base64, url, hint dengan label + position
   - hint menyebut "Tab '<label>' at position <position>" supaya user tahu
     tab mana yang dimaksud saat multi-tab

3. Inform user dengan response natural language:
   - Tampilkan screenshot atau jelaskan apa yang agent lihat
   - Quote hint dari server
   - Minta user konfirmasi setelah solve manual: "Bilang 'lanjut' setelah selesai"

4. Tunggu user konfirmasi. JANGAN polling otomatis — tunggu eksplisit user input.

5. Resume session:
   - panggil smart_session_resume(session_id) setelah user bilang lanjut
   - kalau response state="session_expired" → user tutup browser manual,
     agent perlu reconnect dengan smart_connect_browser baru

6. Continue original workflow dari posisi terakhir.

PRINSIP: Agent = user replacement, BUKAN user replacement diam-diam.
Setiap challenge yang melibatkan privasi/auth/payment HARUS minta konfirmasi user.
Tab counter TIDAK berubah saat pause — session tetap aktif.
"""


# ============================================================================
# Server factory
# ============================================================================


def _register_prompts(mcp: Any) -> None:
    """Register 3 prompts via mcp.prompt() decorator (mcp 1.x/2.x compatible).

    mcp 2.x changed Prompt constructor to require `fn` field. Cleaner
    approach: use `@mcp.prompt(name=..., description=...)` decorator on
    handler functions (works in mcp 1.12+ and 2.x).
    """

    # 1. oauth_confirmation_flow
    @mcp.prompt(
        name="oauth_confirmation_flow",
        description=(
            "Pattern untuk handle OAuth re-authentication flow. "
            "Service URL construction hardcoded per service."
        ),
    )
    async def oauth_confirmation_flow(service: str, scopes: str = "") -> str:
        if not service:
            raise ValueError("oauth_confirmation_flow requires 'service' argument")
        scopes_line = (
            f"   - Scopes needed: {scopes}\n"
            if scopes
            else "   - Scopes: detect dari OAuth provider (default sesuai service)\n"
        )
        auth_url = "<service_url>"  # Phase 1 default; Phase 2 from service catalog
        return _OAUTH_PROMPT_TEMPLATE.format(
            service=service, auth_url=auth_url, scopes_line=scopes_line
        )

    # 2. browser_debug_workflow
    @mcp.prompt(
        name="browser_debug_workflow",
        description="Pattern investigasi UI flow failure pakai DevTools.",
    )
    async def browser_debug_workflow(symptom: str, service: str = "example.com") -> str:
        if not symptom:
            raise ValueError("browser_debug_workflow requires 'symptom' argument")
        return _DEBUG_PROMPT_TEMPLATE.format(service=service)

    # 3. human_intervention_workflow
    @mcp.prompt(
        name="human_intervention_workflow",
        description="Pattern pause + minta user solve CAPTCHA/2FA/manual review.",
    )
    async def human_intervention_workflow(challenge_type: str, context: str = "") -> str:
        if not challenge_type:
            raise ValueError(
                "human_intervention_workflow requires 'challenge_type'"
            )
        return _HUMAN_INTERVENTION_TEMPLATE


def build_server(
    vault: VaultBackend,
    browser_executor: BrowserExecutor,
    license_client: LicenseClient | None = None,
) -> Any:
    """Construct MCP Server wired to vault + browser executor.

    Per refactor/10_mcp_server.md §"Pattern Implementation" line 432-495.

    Implementation note: uses mcp.server.fastmcp.FastMCP (mcp 1.x) or
    mcp.server.mcpserver.MCPServer (mcp 2.x) — same API, renamed in 2.x.
    Provides cleaner add_tool/add_prompt/list_tools() methods vs old
    low-level Server decorators (verified via live stdio test 2026-08-16).
    """
    _FastMCPClass: Any = None
    # Per mcp version: 1.x exposes FastMCP, 2.x renames to MCPServer.
    # We import both conditionally — mcp 2.x not installed on dev machine
    # so ignore_missing_imports applies.
    import_module: Any = None
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F811
        import_module = FastMCP
    except ImportError:
        try:
            from mcp.server.mcpserver import (  # type: ignore[import-not-found]  # noqa: F811
                MCPServer,
            )
            import_module = MCPServer
        except ImportError:
            pass

    if import_module is None:
        raise RuntimeError(
            "mcp package not importable (neither mcp.server.fastmcp nor mcp.server.mcpserver found). "
            "Install mcp>=1.12 or mcp>=2.0."
        )

    mcp = import_module("mcp-env-browser")

    # Register 13 tools via FastMCP add_tool
    for _tool_name, (_schema, _desc) in _TOOL_REGISTRY.items():
        _register_tool(mcp, _tool_name, _schema, _desc, vault, browser_executor)

    # Register 3 prompts via FastMCP add_prompt
    _register_prompts(mcp)

    return mcp


def _build_test_handlers(
    vault: VaultBackend, browser_executor: BrowserExecutor
) -> dict[type[Any], Any]:
    """Test-mode: return raw handler functions keyed by request type.

    Bypasses FastMCP runtime so unit tests can dispatch synchronously without
    needing full MCP server startup. Keys match mcp_types.RequestType values.
    """
    from mcp import types as mcp_types

    async def _list_tools_handler(req: Any = None) -> Any:
        tools = [
            Tool(name=name, description=desc, inputSchema=schema)
            for name, (schema, desc) in _TOOL_REGISTRY.items()
        ]
        return ListToolsResult(tools=tools)

    async def _list_prompts_handler(req: Any = None) -> Any:
        prompts = []
        # oauth
        prompts.append(Prompt(
            name="oauth_confirmation_flow",
            description="Pattern untuk handle OAuth re-authentication flow. Service URL construction hardcoded per service.",
            arguments=[
                PromptArgument(name="service", description="Service identifier (e.g. 'tiktok', 'github').", required=True),
                PromptArgument(name="scopes", description="OAuth scopes yang dibutuhkan (comma-separated, optional).", required=False),
            ],
        ))
        prompts.append(Prompt(
            name="browser_debug_workflow",
            description="Pattern investigasi UI flow failure pakai DevTools (Console + Network + DOM correlate).",
            arguments=[
                PromptArgument(name="symptom", description="Symptom observed by agent", required=True),
                PromptArgument(name="service", description="Service domain (optional)", required=False),
            ],
        ))
        prompts.append(Prompt(
            name="human_intervention_workflow",
            description="Pattern pause + minta user solve CAPTCHA/2FA/manual review.",
            arguments=[
                PromptArgument(name="challenge_type", description="captcha|2fa|...", required=True),
                PromptArgument(name="context", description="Situational context (optional)", required=False),
            ],
        ))
        return ListPromptsResult(prompts=prompts)

    async def _get_prompt_handler(req: Any) -> Any:
        name = req.params.name
        arguments = req.params.arguments or {}
        if name == "oauth_confirmation_flow":
            service = arguments.get("service")
            if not service:
                raise ValueError("oauth_confirmation_flow requires 'service' argument")
            scopes = arguments.get("scopes")
            scopes_line = (
                f"   - Scopes needed: {scopes}\n"
                if scopes
                else "   - Scopes: detect dari OAuth provider (default sesuai service)\n"
            )
            return GetPromptResult(
                description=f"OAuth re-authentication flow for {service}",
                messages=[
                    PromptMessage(role="user", content=TextContent(type="text", text=f"OAuth re-authentication flow untuk {service}")),
                    PromptMessage(role="assistant", content=TextContent(type="text", text=_OAUTH_PROMPT_TEMPLATE.format(
                        service=service,
                        auth_url=arguments.get("auth_url", "<service_url>"),
                        scopes_line=scopes_line,
                    ))),
                ],
            )
        if name == "browser_debug_workflow":
            symptom = arguments.get("symptom")
            if not symptom:
                raise ValueError("browser_debug_workflow requires 'symptom' argument")
            service = arguments.get("service", "example.com")
            return GetPromptResult(
                description=f"Browser debug workflow for {service}",
                messages=[
                    PromptMessage(role="user", content=TextContent(type="text", text=f"Browser debug workflow untuk symptom: {symptom} (service: {service})")),
                    PromptMessage(role="assistant", content=TextContent(type="text", text=_DEBUG_PROMPT_TEMPLATE.format(service=service))),
                ],
            )
        if name == "human_intervention_workflow":
            challenge_type = arguments.get("challenge_type")
            if not challenge_type:
                raise ValueError("human_intervention_workflow requires 'challenge_type'")
            context = arguments.get("context")
            context_suffix = f" ({context})" if context else ""
            return GetPromptResult(
                description="Pause session for human intervention",
                messages=[
                    PromptMessage(role="user", content=TextContent(type="text", text=f"Agent stuck at challenge_type={challenge_type}{context_suffix}, minta pattern user-replacement")),
                    PromptMessage(role="assistant", content=TextContent(type="text", text=_HUMAN_INTERVENTION_TEMPLATE)),
                ],
            )
        raise ValueError(f"unknown prompt: {name}")

    async def _call_tool_handler(req: Any) -> Any:
        import json as _json
        try:
            payload = await _dispatch(req.params.name, req.params.arguments or {}, vault, browser_executor)
            return CallToolResult(
                content=[TextContent(type="text", text=_json.dumps(payload))],
                isError=False,
            )
        except Exception as e:
            logger.exception("mcp tool failed", extra={"tool_name": req.params.name})
            return CallToolResult(
                content=[TextContent(type="text", text=_json.dumps({"ok": False, "error": "internal", "message": str(e)}))],
                isError=True,
            )

    return {
        mcp_types.ListToolsRequest: _list_tools_handler,
        mcp_types.ListPromptsRequest: _list_prompts_handler,
        mcp_types.GetPromptRequest: _get_prompt_handler,
        mcp_types.CallToolRequest: _call_tool_handler,
    }


def _register_tool(
    mcp: Any,
    name: str,
    schema: dict[str, Any],
    description: str,
    vault: VaultBackend,
    browser_executor: BrowserExecutor,
) -> None:
    """Register a single tool via FastMCP add_tool.

    FastMCP.add_tool signature: (fn, name=None, description=None). It
    auto-derives input schema from function signature + type hints.

    Our 13 tools all take **kwargs (variadic) because each has different
    per-action kwargs. The schema dict in _TOOL_REGISTRY is preserved for
    documentation but FastMCP will derive its own from the function.
    """

    async def _tool_handler(args: dict[str, Any]) -> dict[str, Any]:
        # Route through _dispatch (which knows per-tool args).
        # FastMCP signature: must use typed `args: dict` (NOT **kwargs,
        # which gets mis-interpreted as a single string field).
        # JSON-RPC payload: {"name": ..., "arguments": {"target": ..., ...}}
        from mcp_env_browser.mcp_server import _dispatch
        return cast(
            dict[str, Any],
            await _dispatch(name, args, vault, browser_executor),
        )

    # Set proper function metadata for FastMCP introspection
    _tool_handler.__name__ = name
    _tool_handler.__doc__ = description

    mcp.add_tool(
        _tool_handler,
        name=name,
        description=description,
    )


# ============================================================================
# Tool dispatch (separated for testability)
# ============================================================================


async def _dispatch(
    name: str,
    args: dict[str, Any],
    vault: VaultBackend,
    browser_executor: BrowserExecutor,
) -> dict[str, object] | list[dict[str, object]] | object:
    """Route tool call to vault/browser sync methods wrapped via asyncio.to_thread.

    Return type intentionally wide — different tools return different shapes:
    - list_sessions → list[dict]
    - others → dict
    - pause/resume → dict
    - browser_action → dict or any
    """
    # --- credential tools (vault) ---
    if name == "smart_list_credentials":
        return await asyncio.to_thread(
            _list_credentials, vault, args.get("filter")
        )

    if name == "smart_get_credential_meta":
        key = cast(str, args["key"])
        return await asyncio.to_thread(_get_credential_meta, vault, key)

    if name == "smart_set_credential":
        return await asyncio.to_thread(
            _set_credential,
            vault,
            cast(str, args["key"]),
            cast(str, args["type"]),
            cast(dict[str, Any], args["value"]),
        )

    if name == "smart_delete_credential":
        return await asyncio.to_thread(
            _delete_credential, vault, cast(str, args["key"])
        )

    # --- browser tools (browser_executor) ---
    if name == "smart_connect_browser":
        return await asyncio.to_thread(
            browser_executor.connect,
            cast(str, args["target"]),
            cast(str, args["credential_key"]),
            args.get("label"),
        )

    if name == "smart_list_sessions":
        return await asyncio.to_thread(
            browser_executor.list_sessions,
            bool(args.get("include_screenshot", False)),
        )

    if name == "smart_close_browser":
        sid = args.get("session_id")
        return await asyncio.to_thread(browser_executor.close, sid)

    if name == "smart_browser_action":
        sid = cast(str, args["session_id"])
        action = cast(str, args["action"])
        # Extract action kwargs (exclude session_id + action)
        kwargs = {k: v for k, v in args.items() if k not in ("session_id", "action")}
        return await asyncio.to_thread(
            browser_executor.action, sid, action, **kwargs
        )

    if name == "smart_session_pause":
        return await asyncio.to_thread(
            browser_executor.pause_session,
            cast(str, args["session_id"]),
            cast(str, args["reason"]),
        )

    if name == "smart_session_resume":
        return await asyncio.to_thread(
            browser_executor.resume_session,
            cast(str, args["session_id"]),
        )

    # --- CDP-backed tools (lazy create CDPHelpers per session) ---
    if name in (
        "smart_browser_console_log",
        "smart_browser_network_log",
        "smart_browser_inspect",
    ):
        return await asyncio.to_thread(
            _cdp_dispatch, browser_executor, name, args
        )

    raise ValueError(f"unknown tool: {name}")


def _cdp_dispatch(
    browser_executor: BrowserExecutor,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """CDP-backed tool dispatch (sync). Lazily create CDPHelpers per session."""
    from mcp_env_browser.browser.cdp import CDPHelpers

    sid = cast(str, args["session_id"])
    sess = browser_executor.get_session(sid)
    if sess is None:
        raise KeyError(f"session not found: {sid}")
    cdp = CDPHelpers(sess["page"])

    if name == "smart_browser_console_log":
        # Auto-enable console on first call (idempotent — re-subscribe is safe)
        if not cdp._messages:
            cdp.enable_console()
        return {"messages": cdp.get_console_log(level=args.get("type"))}

    if name == "smart_browser_network_log":
        if not cdp._requests:
            cdp.enable_network()
        return {"requests": cdp.get_network_log(filter_text=args.get("filter"))}

    if name == "smart_browser_inspect":
        return cdp.inspect_element(cast(str, args["selector"]))

    raise ValueError(f"unknown CDP tool: {name}")


# ============================================================================
# Sync helpers (vault layer)
# ============================================================================


def _list_credentials(
    vault: VaultBackend, filter_text: str | None
) -> list[dict[str, str]]:
    """List vault credentials (metadata only, NO plaintext)."""
    return vault.list_keys(filter_text)


def _get_credential_meta(vault: VaultBackend, key: str) -> dict[str, Any]:
    """Return metadata for a credential.

    Per refactor/10_mcp_server.md line 86-102:
    Returns {key, type, username, created_at} — NEVER password/value/token.

    Implementation: vault.list_keys() gives us type metadata. Username must be
    parsed from stored value bytes IF type=username_password. For other types,
    we use a summary field from list_keys (no plaintext exposed).

    NOTE: This function does parse the JSON value bytes IF needed for username
    extraction — that's metadata, not the password itself. Spec §10_security
    line 102: "tidak pernah return field password/value/token" — username is OK.
    """
    keys = vault.list_keys(filter_text=None)
    meta = next((k for k in keys if k["key"] == key), None)
    if meta is None:
        raise KeyError(f"credential not found: {key}")
    result: dict[str, Any] = {
        "key": meta["key"],
        "type": meta["type"],
        "summary": meta.get("summary", ""),
    }
    # For username_password, extract username from stored JSON value
    if meta["type"] == "username_password":
        raw = vault.get(key)
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict):
                    result["username"] = parsed.get("username", "")
            except (ValueError, UnicodeDecodeError):
                pass
    return result


def _set_credential(
    vault: VaultBackend, key: str, cred_type: str, value: dict[str, Any]
) -> dict[str, bool]:
    """Save credential to vault (auto-encrypt via libsecret)."""
    vault.set(
        key,
        json.dumps(value).encode("utf-8"),
        attributes={"type": cred_type, "app": "mcp-env-browser"},
    )
    return {"ok": True}


def _delete_credential(vault: VaultBackend, key: str) -> dict[str, bool]:
    """Delete credential from vault."""
    vault.delete(key)
    return {"ok": True}


# ============================================================================
# Stdio entry point (per refactor/10_mcp_server.md §CLI Commands: serve)
# ============================================================================


async def run_stdio_server(
    vault: VaultBackend,
    browser_executor: BrowserExecutor,
    license_client: LicenseClient | None = None,
) -> None:
    """Start MCP stdio server (Phase 8 CLI glue calls this).

    Per refactor/10_mcp_server.md §"Pattern Implementation" line 432-495 +
    §CLI Commands: serve (line 36-43).

    Uses FastMCP/MCPServer.run(transport="stdio") API (mcp 1.x/2.x).
    - mcp 1.12-1.x: FastMCP class
    - mcp 2.x: renamed to MCPServer

    FastMCP/MCPServer handles initialize handshake + JSON-RPC loop internally.

    Note: run() is blocking (synchronous). We run it via asyncio.to_thread()
    to keep event loop alive (so monitor HTTP can co-run).
    """
    # mcp 2.x renamed FastMCP → MCPServer; build_server() already handles
    # both versions internally (see import_module try/except there).
    mcp = cast(Any, build_server(vault, browser_executor, license_client))
    # FastMCP/MCPServer.run() is blocking — run in thread to keep
    # event loop alive (so monitor HTTP can co-run).
    await asyncio.to_thread(mcp.run, "stdio")
