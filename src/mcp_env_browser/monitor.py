"""Web Monitoring Companion — FastAPI app + vanilla JS polling UI.

Per refactor/45_monitoring.md (full spec).

Phase 7 deliverable: localhost:9876 dashboard so user bisa lihat real-time
apa yang sedang agent lakukan di browser, dan click-to-focus untuk intervene
during pause/resume.

Architecture:
- GET /                 → static HTML (monitor.html)
- GET /api/sessions     → list sessions JSON (include_screenshot=true)
- POST /api/sessions/{id}/focus → bring browser window to front
- GET /health           → health check

Phase 8 CLI glues `browser_executor` injection at startup.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

if TYPE_CHECKING:
    from mcp_env_browser.browser import BrowserExecutor

logger = logging.getLogger(__name__)


app = FastAPI(title="mcp-env-browser Monitor")

# Will be injected by CLI at startup (per refactor §45 line 53-54).
# Per refactor §45 line 56-82 spec for endpoints.
browser_executor: BrowserExecutor | None = None


def set_browser_executor(executor: BrowserExecutor) -> None:
    """Inject the BrowserExecutor instance (Phase 8 CLI glue calls this)."""
    global browser_executor  # noqa: PLW0603 — module-level state by design
    browser_executor = executor


@app.get("/api/sessions")
async def list_sessions_endpoint(
    include_screenshot: bool = True,
) -> list[dict[str, Any]]:
    """List semua session aktif dengan screenshot (per refactor §45 line 56-61)."""
    if browser_executor is None:
        raise HTTPException(503, "browser_executor not initialized")
    return browser_executor.list_sessions(include_screenshot=include_screenshot)


@app.post("/api/sessions/{session_id}/focus")
async def focus_session_endpoint(session_id: str) -> dict[str, bool]:
    """Bring browser window + tab ke front (per refactor §45 line 63-72)."""
    if browser_executor is None:
        raise HTTPException(503, "browser_executor not initialized")
    try:
        browser_executor.focus_session(session_id)
        return {"ok": True}
    except KeyError:
        raise HTTPException(404, f"session {session_id} not found") from None


@app.get("/")
async def index_endpoint() -> HTMLResponse:
    """Serve static monitoring page (per refactor §45 line 74-78)."""
    html_path = Path(__file__).parent / "monitor.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/health")
async def health_endpoint() -> dict[str, str]:
    """Health check endpoint (per refactor §45 line 80-82)."""
    return {"status": "ok"}
