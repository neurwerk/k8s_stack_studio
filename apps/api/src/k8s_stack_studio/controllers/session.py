"""Verified caller session exposed to the Studio web application."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_current_principal

router = APIRouter(prefix="/api/session", tags=["session"])


class SessionResponse(BaseModel):
    """Authorization claims from the middleware-verified access token."""

    subject: str
    realm_roles: list[str]
    agentgateway_roles: list[str]


@router.get("")
def get_session(
    principal: StudioPrincipal = Depends(get_current_principal),
) -> SessionResponse:
    """Return stable, sorted authorization claims for the current caller."""
    return SessionResponse(
        subject=principal.subject,
        realm_roles=sorted(principal.roles),
        agentgateway_roles=sorted(principal.agentgateway_roles),
    )
