"""Approved catalog and personal native OAuth, with platform admission kept separate."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.contextforge import ContextForgeAccountClient, ContextForgeAccountError
from k8s_stack_studio.lib.contextforge_oauth import ContextForgeOAuthClient
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings, require_role
from k8s_stack_studio.models.mcp import (
    McpCatalogEntry,
    McpConnectionStatus,
    McpConnectResponse,
    McpRegistration,
)

router = APIRouter(
    prefix="/api/me/mcp", tags=["mcp"], dependencies=[Depends(require_role("studio-user"))]
)


class PrepareAccountRequest(BaseModel):
    """Onboarding accepts no caller-supplied identity, destination or grants."""

    model_config = ConfigDict(extra="forbid")


def _verified_email(principal: StudioPrincipal) -> str:
    email = principal.profile.get("email")
    if (
        not isinstance(email, str)
        or not email.isascii()
        or len(email) > 254
        or principal.profile.get("email_verified") is not True
        or not re.fullmatch(r"[^@\s/\\?#\x00-\x1f\x7f]+@[^@\s/\\?#\x00-\x1f\x7f]+", email)
    ):
        raise HTTPException(status_code=403, detail="A verified account email is required")
    return email.lower()


def _require_connections(settings: Settings = Depends(get_settings)) -> None:
    if not settings.mcp_connections_enabled:
        raise HTTPException(status_code=404, detail="Personal MCP connections are not enabled")


def _connection_admission(
    integration_id: str, principal: StudioPrincipal, settings: Settings
) -> tuple[McpRegistration, str]:
    item = next((item for item in settings.mcp_catalog if item.id == integration_id), None)
    if item is None or item.authentication_model != "individual-authentication":
        raise HTTPException(status_code=404, detail="Personal MCP connection is not available")
    if not {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles:
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    return item, _verified_email(principal)


def _native_unavailable() -> HTTPException:
    return HTTPException(
        status_code=502,
        detail="Native MCP connection is unavailable",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{integration_id}/connect", dependencies=[Depends(_require_connections)])
async def connect(
    integration_id: str,
    body: PrepareAccountRequest,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> McpConnectResponse:
    """Connect/reconnect only by user intent; never accept browser identity or destinations."""
    item, email = _connection_admission(integration_id, principal, settings)
    # Bearer-only Studio auth already prevents ambient-cookie CSRF; also require
    # the operator-approved browser origin for this state-changing OAuth action.
    if request.headers.get("origin") != settings.contextforge_oauth_studio_origin:
        raise HTTPException(status_code=403, detail="Approved Studio origin is required")
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(30):
            await ContextForgeAccountClient(
                settings, request.app.state.contextforge_admin_client
            ).prepare_account(email)
            authorization_url = await ContextForgeOAuthClient(
                settings, request.app.state.contextforge_oauth_client, email
            ).authorize(item)
    except (ContextForgeAccountError, TimeoutError):
        raise _native_unavailable() from None
    callback = urlsplit(settings.contextforge_oauth_callback_url)
    return McpConnectResponse(
        authorization_url=authorization_url,
        callback_origin=f"{callback.scheme}://{callback.netloc}",
    )


@router.get("/{integration_id}/status", dependencies=[Depends(_require_connections)])
async def connection_status(
    integration_id: str,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> McpConnectionStatus:
    """Recheck account, fixed-team membership and grants without restoring revoked access."""
    item, email = _connection_admission(integration_id, principal, settings)
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(30):
            await ContextForgeAccountClient(
                settings, request.app.state.contextforge_admin_client
            ).check_account(email)
            return await ContextForgeOAuthClient(
                settings, request.app.state.contextforge_oauth_client, email
            ).status(item)
    except (ContextForgeAccountError, TimeoutError):
        raise _native_unavailable() from None


@router.post("/account")
async def prepare_account(
    body: PrepareAccountRequest,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Prepare a native account only after verified Studio and MCP admission."""
    if not settings.contextforge_account_onboarding_enabled:
        raise HTTPException(status_code=404, detail="MCP account onboarding is not enabled")
    if not any(
        {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles
        for item in settings.mcp_catalog
    ):
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    email = _verified_email(principal)
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(30):
            await ContextForgeAccountClient(
                settings, request.app.state.contextforge_admin_client
            ).prepare_account(email)
    except (ContextForgeAccountError, TimeoutError):
        raise HTTPException(
            status_code=502,
            detail="Native MCP account preparation is unavailable",
            headers={"Cache-Control": "no-store"},
        ) from None
    return {"status": "ready"}


@router.get("/catalog")
async def get_catalog(
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> list[McpCatalogEntry]:
    """Return only fixed operator labels and the verified caller's platform permission."""
    if not settings.mcp_catalog_enabled:
        raise HTTPException(status_code=404, detail="MCP catalog is not enabled")
    response.headers["Cache-Control"] = "no-store"
    return [
        McpCatalogEntry(
            id=item.id,
            name=item.name,
            authentication_model=item.authentication_model,
            permitted={"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles,
            connection_status=(
                "status unavailable"
                if item.authentication_model == "individual-authentication"
                else None
            ),
        )
        for item in settings.mcp_catalog
    ]
