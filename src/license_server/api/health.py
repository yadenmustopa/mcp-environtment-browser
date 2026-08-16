"""GET /health — no auth, simple health check.

Per refactor/20_license_server.md lines 25-32.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from . import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check — no auth. Returns service version."""
    return HealthResponse(status="ok", version=__version__)
