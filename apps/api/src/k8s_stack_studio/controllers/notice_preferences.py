"""Self-service notice visibility preferences."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.dependencies import get_current_user_id, get_settings
from k8s_stack_studio.notice_store import read, read_overrides, write

router = APIRouter(prefix="/api/me/notice-preferences", tags=["notice-preferences"])
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class UserPreferences(BaseModel):
    """All five independently controlled notice categories."""

    model_config = ConfigDict(extra="forbid")
    show_no_pii: bool
    show_pass: bool
    show_changes: bool
    show_reroutes: bool
    show_timing: bool


class KeyOverrides(BaseModel):
    """Null inherits the matching user preference."""

    model_config = ConfigDict(extra="forbid")
    show_no_pii: bool | None
    show_pass: bool | None
    show_changes: bool | None
    show_reroutes: bool | None
    show_timing: bool | None


def _require_store(settings: Settings = Depends(get_settings)) -> Settings:
    """Reject disabled storage before contacting the bridge or database."""
    if not settings.notice_dsn:
        raise HTTPException(503, "Notice preferences are unavailable")
    return settings


async def _store_call[T](operation: Callable[..., Awaitable[T]], *args: object) -> T:
    """Map unavailable or unmigrated storage to a safe service error."""
    try:
        return await operation(*args)
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError) as exc:
        raise HTTPException(503, "Notice preferences are unavailable") from exc


async def _owned_key(request: Request, user_id: str, key_id: str, settings: Settings) -> None:
    """Ask the bridge using the caller's JWT; fail closed on missing/revoked keys."""
    if not settings.keycloak_api_key_bridge_url:
        raise HTTPException(503, "API key bridge is not configured")
    try:
        response = await request.app.state.http_client.get(
            f"{settings.keycloak_api_key_bridge_url.rstrip('/')}/api_keys",
            params={"user_id": user_id},
            headers={"Authorization": request.headers.get("Authorization", "")},
        )
        response.raise_for_status()
        keys = response.json()
    except Exception as exc:
        raise HTTPException(502, "Unable to verify API key ownership") from exc
    if not isinstance(keys, list):
        raise HTTPException(502, "Invalid API key list")
    if not any(_active_key(key, key_id) for key in keys):
        raise HTTPException(404, "Active API key not found")


def _active_key(key: object, key_id: str) -> bool:
    """Require a non-revoked, non-expired key from the bridge's own list."""
    if not isinstance(key, dict) or key.get("id") != key_id or key.get("revoked") is not False:
        return False
    expiry = key.get("expires_at")
    if not isinstance(expiry, str):
        return False
    try:
        date = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)  # SQLite bridge timestamps are UTC without an offset.
        return date > datetime.now(UTC)
    except ValueError:
        return False


@router.get("")
async def get_user_preferences(
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(_require_store),
) -> UserPreferences:
    """Read only the authenticated user's own effective settings."""
    return UserPreferences(**await _store_call(read, settings.notice_dsn, user_id))


@router.put("")
async def put_user_preferences(
    preferences: UserPreferences,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(_require_store),
) -> UserPreferences:
    """Replace the authenticated user's settings."""
    await _store_call(write, settings.notice_dsn, user_id, preferences.model_dump())
    return preferences


@router.get("/keys/{key_id}")
async def get_key_preferences(
    key_id: Identifier,
    request: Request,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(_require_store),
) -> KeyOverrides:
    """Read raw overrides for an active, owned key."""
    await _owned_key(request, user_id, key_id, settings)
    return KeyOverrides(**await _store_call(read_overrides, settings.notice_dsn, user_id, key_id))


@router.put("/keys/{key_id}")
async def put_key_preferences(
    key_id: Identifier,
    preferences: KeyOverrides,
    request: Request,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(_require_store),
) -> KeyOverrides:
    """Replace overrides after checking key ownership on every write."""
    await _owned_key(request, user_id, key_id, settings)
    await _store_call(write, settings.notice_dsn, user_id, preferences.model_dump(), key_id)
    return preferences
