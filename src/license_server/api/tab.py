"""POST /tab/increment — atomic counter increment per user.

Per refactor/20_license_server.md lines 71-95.
Atomic guarantee: BEGIN IMMEDIATE transaction (see db.py:increment_tab_counter).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import LicenseRepository
from ..dependencies import get_repository
from . import TabIncrementRequest, TabIncrementResponse

router = APIRouter(prefix="/tab", tags=["tab"])


@router.post("/increment", response_model=TabIncrementResponse)
def increment(
    body: TabIncrementRequest,
    repo: LicenseRepository = Depends(get_repository),
) -> TabIncrementResponse:
    """Atomically increment user tab counter.

    Returns:
    - 200 ok + tabs_used + tabs_quota_remaining
    - 401 invalid api key
    - 403 subscription expired / inactive
    - 429 quota exceeded (atomic check — counter unchanged on failure)
    """
    user = repo.get_user_by_api_key(body.api_key)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account inactive",
        )
    if user.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="subscription expired",
        )

    success, tabs_used, tabs_quota = repo.increment_tab_counter(
        user_id=user.id,
        amount=body.amount,
        source="mcp_env_browser",
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "tab quota exceeded",
                "tabs_used": tabs_used,
                "tabs_quota": tabs_quota,
            },
        )

    return TabIncrementResponse(
        ok=True,
        tabs_used=tabs_used,
        tabs_quota_remaining=tabs_quota - tabs_used,
    )
