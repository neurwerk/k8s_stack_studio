"""Per-user call, token, and cost usage routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from k8s_stack_studio.lib.agentgateway import (
    AgentGatewayClient,
    AgentGatewayUsageError,
    InvalidUsageRangeError,
)
from k8s_stack_studio.lib.dependencies import (
    get_agentgateway,
    get_current_user_id,
    require_role,
)
from k8s_stack_studio.models.usage import DailyUsageResponse, UsageResponse

router = APIRouter(prefix="/api/users", tags=["usage"])

CalendarDate = Annotated[str | None, Query(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]


async def _require_self_or_usage_admin(user_id: str, request: Request) -> None:
    """Allow a user to view self usage or a usage admin to view any user."""
    if user_id == get_current_user_id(request):
        return
    require_role("langfuse-admin")(request)


@router.get("/{user_id}/usage/daily", response_model=DailyUsageResponse)
async def get_user_daily_usage(
    user_id: str,
    start: CalendarDate = None,
    end: CalendarDate = None,
    _: None = Depends(_require_self_or_usage_admin),
    agentgateway: AgentGatewayClient = Depends(get_agentgateway),
) -> DailyUsageResponse:
    """Return inclusive per-model days; default to 30 days ending today, maximum 90."""
    try:
        start_date = date.fromisoformat(start) if start is not None else None
        end_date = date.fromisoformat(end) if end is not None else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Dates must be valid YYYY-MM-DD.") from error
    try:
        return await agentgateway.fetch_daily_usage(user_id, start_date, end_date)
    except InvalidUsageRangeError as error:
        raise HTTPException(
            status_code=422,
            detail="Usage range must contain 1 to 90 inclusive days and end no later than today.",
        ) from error
    except AgentGatewayUsageError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Usage analytics are temporarily unavailable.",
        ) from error


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
