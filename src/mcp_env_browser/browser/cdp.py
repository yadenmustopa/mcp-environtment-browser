"""CDPHelpers — Console/Network/DOM helpers via Chrome DevTools Protocol.

Per refactor/30_client_arch.md §cdp.py line 219-273.

Phase 6 implementation. Used by smart_browser_console_log, smart_browser_network_log,
smart_browser_inspect MCP tools.

Public methods (synchronous — Phase 6 MCP handler wraps via asyncio.to_thread):
- enable_console() + get_console_log(level?) — subscribe Console.messageAdded
- enable_network() + get_network_log(filter_text?) — request/response correlation
- inspect_element(selector) — DOM.getDocument + DOM.querySelector + computed style
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class CDPHelpers:
    """Chrome DevTools Protocol helpers per Playwright page.

    Usage (per refactor/30_client_arch.md §cdp.py line 219-273):
        cdp = CDPHelpers(page)
        cdp.enable_console()
        cdp.enable_network()
        # ... after some interactions ...
        console_msgs = cdp.get_console_log(level="error")
        requests = cdp.get_network_log(filter_text="tiktok.com")
        element_info = cdp.inspect_element(".submit-btn")
    """

    def __init__(self, page: Page) -> None:
        self._page = page
        # Lazy: cdp session is created on first enable_*() call.
        # This way if agent only uses one of console/network/DOM,
        # we don't pay the overhead of all three.
        self._client: Any | None = None
        self._messages: list[dict[str, Any]] = []
        self._requests: dict[str, dict[str, Any]] = {}

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._page.context.new_cdp_session(self._page)
        return self._client

    # --- console ---

    def enable_console(self) -> None:
        """Subscribe to Console.messageAdded events."""
        client = self._get_client()
        client.send("Console.enable")
        # Bind event handler; CDP client .on(event, callback)
        client.on("Console.messageAdded", self._on_console_message)

    def _on_console_message(self, event: dict[str, Any]) -> None:
        """Append incoming console message (per refactor §30 line 229)."""
        # CDP event shape: {"message": {"level": "...", "text": "...", "url": "...", ...}}
        msg = event.get("message", {})
        self._messages.append(
            {
                "level": msg.get("level", "log"),
                "text": msg.get("text", ""),
                "url": msg.get("url"),
                "timestamp": time.time(),
            }
        )

    def get_console_log(self, level: str | None = None) -> list[dict[str, Any]]:
        """Return captured console messages, optionally filtered by level.

        Per refactor §30 line 231-234 + 10_mcp_server.md line 311-326.
        """
        if level:
            return [m for m in self._messages if m["level"] == level]
        return list(self._messages)

    # --- network ---

    def enable_network(self) -> None:
        """Subscribe to Network.requestWillBeSent + Network.responseReceived."""
        client = self._get_client()
        client.send("Network.enable")
        client.on("Network.requestWillBeSent", self._on_request)
        client.on("Network.responseReceived", self._on_response)

    def _on_request(self, event: dict[str, Any]) -> None:
        """Record request metadata (per refactor §30 line 242-247)."""
        request = event.get("request", {})
        self._requests[event["requestId"]] = {
            "url": request.get("url", ""),
            "method": request.get("method", "GET"),
            "started_at": time.time(),
            "status": None,
            "duration_ms": None,
        }

    def _on_response(self, event: dict[str, Any]) -> None:
        """Pair response with request, compute duration."""
        rid = event.get("requestId", "")
        response = event.get("response", {})
        if rid in self._requests:
            entry = self._requests[rid]
            entry["status"] = response.get("status")
            entry["duration_ms"] = int((time.time() - entry["started_at"]) * 1000)

    def get_network_log(self, filter_text: str | None = None) -> list[dict[str, Any]]:
        """Return captured requests, optionally filtered by URL substring.

        Per refactor §30 line 255-257 + 10_mcp_server.md line 328-343.
        """
        items = [
            r for r in self._requests.values() if not filter_text or filter_text in r["url"]
        ]
        return items

    # --- DOM inspect ---

    def inspect_element(self, selector: str) -> dict[str, Any]:
        """Inspect a DOM element: tag, attrs, computed_style, children_count.

        Per refactor §30 line 259-272 + 10_mcp_server.md line 346-359.
        Returns a dict suitable for JSON serialization (TextContent).
        """
        client = self._get_client()

        # Walk the DOM tree to the matching node
        doc = client.send("DOM.getDocument")
        root_node_id = doc.get("root", {}).get("nodeId")
        query_result = client.send(
            "DOM.querySelector",
            {"nodeId": root_node_id, "selector": selector},
        )
        node_id = query_result.get("nodeId")
        if node_id is None or node_id == 0:
            return {
                "found": False,
                "selector": selector,
                "error": "element not found",
            }

        # Describe node (gives us tagName, attributes)
        describe = client.send("DOM.describeNode", {"nodeId": node_id})
        node = describe.get("node", {})

        attrs_list: list[str] = node.get("attributes", []) or []
        attrs: dict[str, str] = {}
        # CDP attributes are flat list [name1, value1, name2, value2, ...]
        for i in range(0, len(attrs_list) - 1, 2):
            attrs[attrs_list[i]] = attrs_list[i + 1]

        # Computed style
        try:
            computed_raw = client.send(
                "CSS.getComputedStyle",
                {"nodeId": node_id},
            )
            computed = self._parse_computed_style(computed_raw)
        except Exception as e:  # CSS domain might not be enabled
            computed = {"_error": str(e)}

        # Children count
        try:
            children = client.send("DOM.getChildNodeCount", {"nodeId": node_id})
            children_count = children.get("childNodeCount", 0)
        except Exception:
            children_count = 0

        outer_html = node.get("outerHTML", "") or ""
        truncated_html = outer_html[:500] + ("..." if len(outer_html) > 500 else "")

        return {
            "found": True,
            "selector": selector,
            "tag": node.get("nodeName", "").lower(),
            "attrs": attrs,
            "computed_style": computed,
            "children_count": children_count,
            "outer_html_truncated": truncated_html,
        }

    def _parse_computed_style(self, raw: dict[str, Any]) -> dict[str, str]:
        """Reduce CDP computed style array to {property: value} dict.

        Per refactor §30 line 270 (parse_computed stub).
        """
        result: dict[str, str] = {}
        for entry in raw.get("computedStyle", []) or []:
            name = entry.get("name")
            value = entry.get("value")
            if name and value is not None:
                # Limit to common properties to keep payload small
                if name in (
                    "display",
                    "visibility",
                    "color",
                    "background-color",
                    "font-size",
                    "font-weight",
                    "width",
                    "height",
                    "position",
                    "opacity",
                ):
                    result[name] = value
        return result
