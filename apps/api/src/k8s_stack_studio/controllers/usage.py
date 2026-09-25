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
from k8s_stack_studio.models.usage import DailyUsageResponse, UsagePeopleResponse, UsageResponse

router = APIRouter(prefix="/api/users", tags=["usage"])
aggregate_router = APIRouter(prefix="/api/usage", tags=["usage"])

CalendarDate = Annotated[str | None, Query(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]


def _parse_dates(start: CalendarDate, end: CalendarDate) -> tuple[date | None, date | None]:
    """Parse calendar dates identically for self and admin views."""
    try:
        return (
            date.fromisoformat(start) if start is not None else None,
            date.fromisoformat(end) if end is not None else None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Dates must be valid YYYY-MM-DD.") from error


def _invalid_range(error: InvalidUsageRangeError) -> HTTPException:
    """Return a consistent, safe date range error."""
    return HTTPException(
        status_code=422,
        detail="Usage range must contain 1 to 90 inclusive days and end no later than today.",
    )


def _usage_unavailable(error: AgentGatewayUsageError) -> HTTPException:
    """Never reveal private analytics response content to callers."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Usage analytics are temporarily unavailable.",
    )


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
    start_date, end_date = _parse_dates(start, end)
    try:
        return await agentgateway.fetch_daily_usage(user_id, start_date, end_date)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except AgentGatewayUsageError as error:
        raise _usage_unavailable(error) from error


@aggregate_router.get("/daily", response_model=DailyUsageResponse)
async def get_all_daily_usage(
    start: CalendarDate = None,
    end: CalendarDate = None,
    _: None = Depends(require_role("langfuse-admin")),
    agentgateway: AgentGatewayClient = Depends(get_agentgateway),
) -> DailyUsageResponse:
    """Aggregate daily model usage; only usage admins may omit the user filter."""
    start_date, end_date = _parse_dates(start, end)
    try:
        return await agentgateway.fetch_all_daily_usage(start_date, end_date)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except AgentGatewayUsageError as error:
        raise _usage_unavailable(error) from error


@aggregate_router.get("/people", response_model=UsagePeopleResponse)
async def get_usage_people(
    start: CalendarDate = None,
    end: CalendarDate = None,
    _: None = Depends(require_role("langfuse-admin")),
    agentgateway: AgentGatewayClient = Depends(get_agentgateway),
) -> UsagePeopleResponse:
    """List only active attributed principals for the admin picker and chart."""
    start_date, end_date = _parse_dates(start, end)
    try:
        return await agentgateway.fetch_user_breakdown(start_date, end_date)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except AgentGatewayUsageError as error:
        raise _usage_unavailable(error) from error


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
        raise _usage_unavailable(error) from error
