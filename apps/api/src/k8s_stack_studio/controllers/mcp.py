"""Authenticated read-only catalog; connection controls await safe native APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings, require_role
from k8s_stack_studio.models.mcp import McpCatalogEntry

router = APIRouter(
    prefix="/api/me/mcp", tags=["mcp"], dependencies=[Depends(require_role("studio-user"))]
)


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
