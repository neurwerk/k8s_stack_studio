"""Authenticated read-only catalog; connection controls await safe native APIs."""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.contextforge import ContextForgeAccountClient, ContextForgeAccountError
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings, require_role
from k8s_stack_studio.models.mcp import McpCatalogEntry

router = APIRouter(
    prefix="/api/me/mcp", tags=["mcp"], dependencies=[Depends(require_role("studio-user"))]
)


class PrepareAccountRequest(BaseModel):
    """Onboarding accepts no caller-supplied identity, destination or grants."""

    model_config = ConfigDict(extra="forbid")


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
    email = principal.profile.get("email")
    if (
        not isinstance(email, str)
        or len(email) > 254
        or principal.profile.get("email_verified") is not True
        or not re.fullmatch(r"[^@\s/\\?#\x00-\x1f\x7f]+@[^@\s/\\?#\x00-\x1f\x7f]+", email)
    ):
        raise HTTPException(status_code=403, detail="A verified account email is required")
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(30):
            await ContextForgeAccountClient(
                settings, request.app.state.contextforge_admin_client
            ).prepare_account(email.lower())
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
