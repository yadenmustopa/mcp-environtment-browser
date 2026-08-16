"""FastAPI app + uvicorn entry point untuk license server (Phase 2).

Per refactor/20_license_server.md §server.py + §Deployment (Phase 1 popOS).
Per knowledge.md §5 FastAPI pattern.

Entry point `run()` registered di pyproject.toml [project.scripts] sebagai
'mcp-env-browser-license-server' (per 40_distribution.md + 30_client_arch.md line 372).
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

from . import __version__
from .api import health, license, tab
from .db import init_db
from .dependencies import get_db_path

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize DB on startup; chmod 600 per security note."""
    db_path: Path = get_db_path()
    app.state.db_path = db_path
    init_db(db_path)
    if db_path.exists():
        db_path.chmod(0o600)
    logger.info("license_server ready: db=%s", db_path)
    yield
    logger.info("license_server shutdown")


app = FastAPI(
    title="mcp-env-browser License Server",
    description="Phase 2 (Strategi A): FastAPI license DB + per-tab counter.",
    version=__version__,
    lifespan=lifespan,
)

# Mount routers (per refactor/00_overview.md §File Map api/{health,license,tab}.py)
app.include_router(health.router)
app.include_router(license.router)
app.include_router(tab.router)


@app.get("/", include_in_schema=False)
def root(request: Request) -> dict[str, str]:
    """Landing endpoint for sanity check."""
    return {
        "service": "mcp-env-browser license server",
        "version": __version__,
        "endpoints": "/health, /license/check, /license/register (admin), /tab/increment",
        "docs": "/docs",
    }


def run() -> None:
    """CLI entry point `mcp-env-browser-license-server`.

    Per refactor/20_license_server.md §Deployment lines 174-205.
    Env var defaults:
    - MCP_LICENSE_PORT (default 8765)
    - MCP_LICENSE_HOST (default 127.0.0.1 — localhost only per security model)
    - MCP_LICENSE_DB_PATH (default ~/.local/share/mcp-env-browser/license.sqlite3)
    - MCP_LICENSE_WORKERS (default 1 — multi-worker not Phase 1 safe per knowledge.md §5)
    """
    parser = argparse.ArgumentParser(
        prog="mcp-env-browser-license-server",
        description="License DB + per-tab counter for mcp-env-browser Phase 2.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_LICENSE_PORT", "8765")),
        help="Bind port (default: 8765, env: MCP_LICENSE_PORT).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("MCP_LICENSE_HOST", "127.0.0.1"),
        help="Bind host (default: 127.0.0.1 — localhost only).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("MCP_LICENSE_WORKERS", "1")),
        help="uvicorn workers (Phase 1 MUST be 1 — SQLite single-writer).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("MCP_LICENSE_LOG_LEVEL", "info"),
        choices=["debug", "info", "warning", "error"],
    )
    args = parser.parse_args()

    if args.workers > 1:
        raise SystemExit(
            f"--workers {args.workers} not supported in Phase 1 "
            "(SQLite single-writer model per knowledge.md §5). "
            "Use --workers 1 (default) or migrate to Postgres in Phase 2+."
        )

    logger.info(
        "Starting mcp-env-browser license server v%s on %s:%s (workers=%d)",
        __version__,
        args.host,
        args.port,
        args.workers,
    )
    uvicorn.run(
        "license_server.server:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    run()
