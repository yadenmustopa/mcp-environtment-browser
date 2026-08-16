"""Pydantic v2 request/response models untuk license server endpoints.

Per refactor/20_license_server.md §Endpoints lines 25-130 + knowledge.md §5.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LicenseCheckRequest(BaseModel):
    """POST /license/check body."""

    api_key: str = Field(min_length=1, description="32-char hex API key")


class LicenseCheckResponse(BaseModel):
    """200 response."""

    valid: bool
    plan: str
    tabs_used: int
    tabs_quota: int
    expires_at: str  # ISO 8601


class TabIncrementRequest(BaseModel):
    """POST /tab/increment body."""

    api_key: str = Field(min_length=1)
    amount: int = Field(default=1, ge=0, description="Tabs to add (Phase 1 only >=0)")  # noqa: S107


class TabIncrementResponse(BaseModel):
    """200 response."""

    ok: bool
    tabs_used: int
    tabs_quota_remaining: int


class LicenseRegisterRequest(BaseModel):
    """POST /license/register body (admin)."""

    email: EmailStr
    plan: str = "dev"
    tabs_quota: int = Field(default=10000, gt=0)
    expires_in_days: int = Field(default=365, gt=0)


class LicenseRegisterResponse(BaseModel):
    """200 response — returns fresh api_key (one-time visible)."""

    api_key: str
    email: str
    plan: str
    expires_at: str


class HealthResponse(BaseModel):
    """GET /health — no auth."""

    status: str
    version: str
