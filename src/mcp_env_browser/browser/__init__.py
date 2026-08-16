"""BrowserExecutor — Playwright wrapper + per-tab counter hook (Phase 5).

Per refactor/30_client_arch.md §Browser Module + knowledge.md §3 Playwright.

Goal flow:
1. smart_connect_browser(target, credential_key, label?) called
2. LicenseClient.check() → 200 valid (else raise)
3. LicenseClient.increment(amount=1) → 200 ok (else raise quota_exceeded)
4. BrowserExecutor._ensure_browser()
5. context.new_page()  ← THIS IS the per-tab counter trigger (K1)
6. Auto-login via credential (workflow hardcoded per target Phase 1)
7. session stored, return {session_id, label, position, page_handle}

Phase 6 MCP tool handler akan wrap method sync ini dengan `asyncio.to_thread()`
per spec 10_mcp_server.md §"Async Pattern".
"""

from __future__ import annotations

import base64
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page

    from mcp_env_browser.license import LicenseClient
    from mcp_env_browser.vault import VaultBackend

logger = logging.getLogger(__name__)

# Lazy import of sync_playwright — only when connect_browser() is first called
# This way we don't fail at import time if Playwright not installed.

DEFAULT_TYPING_DELAY_MS = 50  # per refactor/30_client_arch.md line 264
DEFAULT_TYPING_JITTER_MS = 20


class BrowserExecutor:
    """Wraps Playwright + per-tab counter (K1) + multi-tab clarity (G6.1).

    Public methods are synchronous — Phase 6 MCP tool handler wraps them
    with asyncio.to_thread() per spec 10_mcp_server.md §"Async Pattern".
    """

    def __init__(
        self,
        license_client: LicenseClient,
        vault: VaultBackend,
        headless: bool = False,
    ) -> None:
        self._license_client = license_client
        self._vault = vault
        self._headless = headless
        self._playwright: Any | None = None
        self._browser: Browser | None = None
        self._sessions: dict[str, dict[str, Any]] = {}
        self._next_position = 0

    # --- public API (callable from Phase 6 MCP tools) ---

    def connect(
        self,
        target: str,
        credential_key: str,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Open browser session per smart_connect_browser tool semantics.

        Order (per refactor/30_client_arch.md §Browser Module line 168-186):
        1. Resolve credential from vault (NEVER return plaintext to caller)
        2. LicenseClient.check() → 200 valid (else raise)
        3. LicenseClient.increment(amount=1) → 200 ok (else raise quota_exceeded)
        4. _ensure_browser() — lazy launch
        5. context.new_page()
        6. page.goto target
        7. auto-login via credential
        8. session storage + return
        """
        # 1. vault.get (plaintext — used internally only)
        cred_value = self._vault.get(credential_key)
        if cred_value is None:
            raise ValueError(f"credential not found: {credential_key}")

        # 2. License check
        check = self._license_client.check()
        if not check.get("valid"):
            raise PermissionError(
                f"license invalid: {check.get('error', 'unknown')}"
            )

        # 3. Per-tab counter increment (K1 atomic per spec §6.3)
        inc = self._license_client.increment(amount=1)
        if not cast(bool, inc.get("ok")):
            if inc.get("quota_exceeded"):
                detail = cast(dict[str, Any], inc.get("detail") or {})
                tabs_used = detail.get("tabs_used", "unknown")
                raise PermissionError(f"tab quota exceeded: tabs_used={tabs_used}")
            raise PermissionError(
                f"license increment failed: {inc.get('error', 'unknown')}"
            )

        # 4. Ensure browser
        self._ensure_browser()
        assert self._browser is not None

        # 5+6. New page + goto target (Playwright sync APIs wrapped)
        page: Page = self._browser.new_page()
        page.goto(target)

        # 7. Auto-login (Phase 1: minimal — fill username/password if standard form)
        # Full workflows per target adalah Phase 6+ MCP prompts (human_intervention).
        # For Phase 5, we just hand-off session ke caller without scripted login.

        # 8. Session dict
        session_id = uuid.uuid4().hex
        position = self._next_position
        self._next_position += 1

        effective_label = label if label else default_label_from_url(target)
        self._sessions[session_id] = {
            "session_id": session_id,
            "credential_key": credential_key,
            "label": effective_label,
            "position": position,
            "target": target,
            "page": page,
            "context": page.context,
            "paused": False,
            "paused_at": None,
            "pause_reason": None,
            "created_at": _now_iso(),
            "url": target,
            "age_seconds": 0,
            "status": "active",
        }

        logger.info(
            "browser session created: id=%s label=%r position=%d",
            session_id,
            effective_label,
            position,
        )

        return {
            "session_id": session_id,
            "label": effective_label,
            "position": position,
            "page_handle": f"page_{session_id}",
        }

    def list_sessions(
        self, include_screenshot: bool = False
    ) -> list[dict[str, Any]]:
        """Return list of active sessions, sorted by position (left-to-right)."""
        results: list[dict[str, Any]] = []
        for sid, sess in sorted(
            self._sessions.items(), key=lambda kv: kv[1]["position"]
        ):
            entry: dict[str, Any] = {
                "session_id": sess["session_id"],
                "label": sess["label"],
                "position": sess["position"],
                "url": sess["url"],
                "status": sess["status"],
                "age_seconds": _now_age_seconds(sess["created_at"]),
            }
            if include_screenshot:
                try:
                    page: Page = sess["page"]
                    png_bytes = page.screenshot()
                    entry["last_screenshot_b64"] = base64.b64encode(png_bytes).decode(
                        "ascii"
                    )
                except Exception as e:
                    logger.debug("screenshot failed for %s: %s", sid, e)
                    entry["last_screenshot_b64"] = None
            results.append(entry)
        return results

    def focus_session(self, session_id: str) -> None:
        """Bring browser window + tab to front."""
        sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"session not found: {session_id}")
        page: Page = sess["page"]
        try:
            page.bring_to_front()
        except Exception as e:
            logger.warning("focus_session %s: %s", session_id, e)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str | None = None) -> dict[str, Any]:
        """Close one session or all sessions (per smart_close_browser tool)."""
        if session_id is None:
            # Close all
            for sid in list(self._sessions.keys()):
                self.close(sid)
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            return {"ok": True}

        if session_id in self._sessions:
            sess = self._sessions[session_id]
            try:
                ctx: BrowserContext = sess["context"]
                ctx.close()
            except Exception:
                pass
            del self._sessions[session_id]
        return {"ok": True}

    # --- session pause/resume (Phase 6 will use this) ---

    def pause_session(self, session_id: str, reason: str) -> dict[str, Any]:
        """Mark session paused + capture screenshot for user intervention.

        Per refactor/30_client_arch.md line 197-217 + refactor/10_mcp_server.md line 597-655.
        """
        sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"session not found: {session_id}")

        page: Page = sess["page"]
        url = page.url
        try:
            png_bytes = page.screenshot(full_page=False)
        except Exception as e:
            logger.warning("pause screenshot failed: %s", e)
            png_bytes = b""

        b64 = base64.b64encode(png_bytes).decode("ascii")

        sess["paused"] = True
        sess["paused_at"] = _now_iso()
        sess["pause_reason"] = reason
        sess["status"] = "paused"

        return {
            "paused": True,
            "screenshot_base64": b64,
            "url": url,
            "label": sess["label"],
            "position": sess["position"],
            "session_id": session_id,
            "paused_at": sess["paused_at"],
            "hint": _pause_hint(reason, sess["label"], sess["position"]),
        }

    def resume_session(self, session_id: str) -> dict[str, Any]:
        """Verify session still alive after pause, return fresh page_handle."""
        sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"session not found: {session_id}")
        if not sess.get("paused"):
            raise ValueError(f"session {session_id} not paused")

        sess["paused"] = False
        sess["status"] = "active"

        page: Page = sess["page"]
        try:
            current_url = page.url
            page.title()
            valid = True
        except Exception:
            valid = False
            current_url = None

        return {
            "ok": valid,
            "resumed": valid,
            "page_handle": f"page_{session_id}" if valid else None,
            "state": "active" if valid else "session_expired",
            "url": current_url,
        }

    # --- browser action dispatch (Phase 6 will call this) ---

    def action(self, session_id: str, action: str, **kwargs: object) -> object:
        """Dispatch browser action per smart_browser_action tool.

        Per refactor/10_mcp_server.md §smart_browser_action:
        navigate | click | type | scroll | drag | hover | screenshot |
        wait_for_selector | wait_for_navigation | evaluate |
        select_option | press_key
        """
        sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"session not found: {session_id}")

        page: Page = sess["page"]

        # Special case: realistic typing with jitter (per 30_client_arch.md line 264)
        if action == "type":
            text = cast(str, kwargs.get("text"))
            delay_ms = int(cast(int, kwargs.get("delay_ms", DEFAULT_TYPING_DELAY_MS)))
            for char in text:
                page.keyboard.type(
                    char,
                    delay=random.randint(
                        delay_ms - DEFAULT_TYPING_JITTER_MS,
                        delay_ms + DEFAULT_TYPING_JITTER_MS,
                    ),
                )
            return {"ok": True}

        handler = _ACTION_HANDLERS.get(action)
        if handler is None:
            raise ValueError(f"unknown action: {action}")

        return handler(page, **kwargs)

    # --- internals ---

    def _ensure_browser(self) -> None:
        """Lazy launch Chromium (Playwright sync)."""
        if self._browser is not None:
            return
        # Lazy import
        from playwright.sync_api import sync_playwright

        if self._playwright is None:
            self._playwright = sync_playwright().start()
        # Phase 1: headless=False (knowledge §3 — TikTok/Google blocking)
        self._browser = self._playwright.chromium.launch(headless=self._headless)


# Per refactor/30_client_arch.md line 293-306
_ACTION_HANDLERS: dict[str, Any] = {
    "navigate": lambda p, **kw: p.goto(cast(str, kw["url"])),
    "click": lambda p, **kw: p.click(cast(str, kw["selector"]), timeout=5000),
    "scroll": lambda p, **kw: p.mouse.wheel(
        0,
        cast(int, kw["amount"])
        if kw.get("direction", "down") == "down"
        else -cast(int, kw["amount"]),
    ),
    "drag": lambda p, **kw: p.locator(cast(str, kw["from_selector"])).drag_to(
        p.locator(cast(str, kw["to_selector"]))
    ),
    "hover": lambda p, **kw: p.locator(cast(str, kw["selector"])).hover(),
    "screenshot": lambda p, **kw: {
        # Per spec §6.4 + refactor/10_mcp_server.md line 268:
        # clip = {x, y, width, height} in CSS pixels (optional)
        # full_page = bool (optional, default false)
        "base64": base64.b64encode(
            p.screenshot(
                full_page=bool(kw.get("full_page", False)),
                clip=kw.get("clip"),
            )
        ).decode()
    },
    "wait_for_selector": lambda p, **kw: p.locator(cast(str, kw["selector"])).wait_for(
        timeout=int(cast(int, kw.get("timeout_ms", 5000)))
    ),
    "wait_for_navigation": lambda p, **kw: p.wait_for_url(
        "**", timeout=int(cast(int, kw.get("timeout_ms", 10000)))
    ),
    "evaluate": lambda p, **kw: p.evaluate(cast(str, kw["js_code"])),
    "select_option": lambda p, **kw: p.select_option(
        cast(str, kw["selector"]), cast(str, kw["value"])
    ),
    "press_key": lambda p, **kw: p.keyboard.press(cast(str, kw["key"])),
}


# --- helper functions ---


def default_label_from_url(url: str) -> str:
    """Per refactor/10_mcp_server.md line 180-189: derive label from domain."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    parts = domain.split(".")
    if len(parts) >= 2:
        return parts[0].capitalize()
    return domain.capitalize() if domain else "Unnamed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_age_seconds(created_iso: str) -> int:
    created = datetime.fromisoformat(created_iso)
    return int((datetime.now(timezone.utc) - created).total_seconds())


_PAUSE_HINTS = {
    "captcha": "Please solve the CAPTCHA in the open browser window.",
    "2fa": "Please enter the OTP code from your authenticator app.",
    "purchase_confirmation": "Please review and confirm the purchase in the browser.",
    "tos_accept": "Please review and accept the Terms of Service.",
    "manual_review": "Your input is required to continue.",
    "other": "Manual intervention required to continue.",
}


def _pause_hint(reason: str, label: str, position: int) -> str:
    """Enhanced hint with label + position for multi-tab clarity (per spec §6.4)."""
    base = _PAUSE_HINTS.get(reason, _PAUSE_HINTS["other"])
    return f"{base} (Tab '{label}' at position {position})"
