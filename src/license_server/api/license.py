"""POST /license/check + POST /license/register (admin).

Per refactor/20_license_server.md lines 35-129.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import LicenseRepository
from ..dependencies import (
    get_repository,
    require_admin,
)
from . import (
    LicenseCheckRequest,
    LicenseCheckResponse,
    LicenseRegisterRequest,
    LicenseRegisterResponse,
)

router = APIRouter(prefix="/license", tags=["license"])


@router.post("/check", response_model=LicenseCheckResponse)
def check(
    body: LicenseCheckRequest,
    repo: LicenseRepository = Depends(get_repository),
) -> LicenseCheckResponse:
    """Validate API key, return license info.

    Per 20_license_server.md lines 38-67:
    - 200: valid (quota check deferred to /tab/increment)
    - 401: invalid api key
    - 403: subscription expired
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
    return LicenseCheckResponse(
        valid=True,
        plan=user.plan,
        tabs_used=user.tabs_used,
        tabs_quota=user.tabs_quota,
        expires_at=user.expires_at.isoformat(),
    )


@router.post("/register", response_model=LicenseRegisterResponse)
def register(
    body: LicenseRegisterRequest,
    repo: LicenseRepository = Depends(get_repository),
    _admin_ok: bool = Depends(require_admin),
) -> LicenseRegisterResponse:
    """Register new user (admin only). Returns fresh api_key ONCE.

    Per 20_license_server.md lines 116-129.
    """
    try:
        user = repo.register_user(
            email=body.email,
            plan=body.plan,
            tabs_quota=body.tabs_quota,
            expires_in_days=body.expires_in_days,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    return LicenseRegisterResponse(
        api_key=user.api_key,
        email=user.email,
        plan=user.plan,
        expires_at=user.expires_at.isoformat(),
    )
