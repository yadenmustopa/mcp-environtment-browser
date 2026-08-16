"""FastAPI dependencies untuk license server endpoints.

Per refactor/20_license_server.md (admin auth, repository injection).
Per AGENTS.md §5 — keep minimal for Phase 1.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Generator
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status

from .db import LicenseRepository, init_db

ADMIN_TOKEN_ENV = "MCP_ADMIN_TOKEN"
DEFAULT_DB_PATH = Path("~/.local/share/mcp-env-browser/license.sqlite3")


def get_db_path() -> Path:
    """Resolve DB path from env MCP_LICENSE_DB_PATH, else default."""
    raw = os.environ.get("MCP_LICENSE_DB_PATH")
    return Path(raw).expanduser() if raw else DEFAULT_DB_PATH.expanduser()


def get_repository(request: Request) -> Generator[LicenseRepository, None, None]:
    """FastAPI dependency: provide LicenseRepository.

    Repository constructed per request (cheap = just sqlite3 wrapper).
    DB path comes from app.state.db_path (set by lifespan in server.py).
    """
    db_path: Path = getattr(request.app.state, "db_path", None) or get_db_path()
    if not db_path.exists():
        init_db(db_path)
    yield LicenseRepository(db_path)


def _extract_admin_header(request: Request) -> str | None:
    """Extract X-Admin-Token header (FastAPI dependency helper)."""
    return request.headers.get("X-Admin-Token")


def require_admin(
    token: str | None = Depends(_extract_admin_header),
) -> bool:
    """Verify X-Admin-Token matches env MCP_ADMIN_TOKEN. Raises 401/403 if not.

    Per refactor/20_license_server.md line 118 (admin token env var).
    Per AGENTS.md §5 — minimal Phase 1 protection.
    """
    expected = os.environ.get(ADMIN_TOKEN_ENV, "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"admin endpoints disabled — set {ADMIN_TOKEN_ENV}",
        )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Admin-Token header required",
        )
    if not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid admin token",
        )
    return True
