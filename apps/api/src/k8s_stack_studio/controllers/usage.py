"""Per-user call, token, and cost usage routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from k8s_stack_studio.lib.agentgateway import AgentGatewayClient, AgentGatewayUsageError
from k8s_stack_studio.lib.dependencies import (
    get_agentgateway,
    get_current_user_id,
    require_role,
)
from k8s_stack_studio.models.usage import UsageResponse

router = APIRouter(prefix="/api/users", tags=["usage"])


async def _require_self_or_usage_admin(user_id: str, request: Request) -> None:
    """Allow a user to view self usage or a usage admin to view any user."""
    if user_id == get_current_user_id(request):
        return
    require_role("langfuse-admin")(request)


@router.get("/{user_id}/usage", response_model=UsageResponse)
async def get_user_usage(
    user_id: str,
    _: None = Depends(_require_self_or_usage_admin),
    agentgateway: AgentGatewayClient = Depends(get_agentgateway),
) -> UsageResponse:
    """Return call, token, and cost usage for one Keycloak user UUID."""
    try:
        return await agentgateway.fetch_usage(user_id)
    except AgentGatewayUsageError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Usage analytics are temporarily unavailable.",
        ) from error
