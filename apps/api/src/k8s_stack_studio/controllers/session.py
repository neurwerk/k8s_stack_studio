"""Verified caller session exposed to the Studio web application."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings
from k8s_stack_studio.notice_store import schema_ready

router = APIRouter(prefix="/api/session", tags=["session"])


class SessionResponse(BaseModel):
    """Authorization claims from the middleware-verified access token."""

    subject: str
    realm_roles: list[str]
    agentgateway_roles: list[str]
    notice_preferences_available: bool
    llm_logs_available: bool


@router.get("")
async def get_session(
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    """Return stable, sorted authorization claims for the current caller."""
    return SessionResponse(
        subject=principal.subject,
        realm_roles=sorted(principal.roles),
        agentgateway_roles=sorted(principal.agentgateway_roles),
        notice_preferences_available=await schema_ready(settings.notice_dsn),
        llm_logs_available=settings.llm_logs_enabled,
    )
