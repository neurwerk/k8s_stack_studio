"""Per-user call, token, and cost usage routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from studio_collector.models import InvalidUsageRangeError
from studio_collector.pricing import ProviderEstimate

from k8s_stack_studio.lib.dependencies import (
    get_current_user_id,
    get_usage,
    require_role,
)
from k8s_stack_studio.lib.usage import UsageReader, UsageUnavailable
from k8s_stack_studio.lib.usage_names import resolve_usage_key_names
from k8s_stack_studio.models.gateway_metadata import UsageFilters, UsageQuery
from k8s_stack_studio.models.usage import (
    DailyUsageResponse,
    UsagePeopleResponse,
    UsageResponse,
    UsageSourcesResponse,
)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/users", tags=["usage"], dependencies=[Depends(_no_store)])
aggregate_router = APIRouter(prefix="/api/usage", tags=["usage"], dependencies=[Depends(_no_store)])


@aggregate_router.get("/billing", response_model=list[ProviderEstimate])
async def get_provider_billing(
    day: date,
    _: None = Depends(require_role("langfuse-admin")),
    reporting: UsageReader = Depends(get_usage),
) -> list[ProviderEstimate]:
    """Account-wide estimates, intentionally separate from scoped gross tool costs."""
    try:
        return await reporting.fetch_billing(day)
    except UsageUnavailable as error:
        raise _usage_unavailable(error) from error


def _parse_dates(start: str | None, end: str | None) -> tuple[date | None, date | None]:
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
        detail="Usage range must contain 1 to 3660 days and end no later than today. "
        "Daily request-ID lookup is limited to 90 days.",
    )


def _usage_unavailable(error: UsageUnavailable) -> HTTPException:
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
    filters: Annotated[UsageQuery, Query()],
    _: None = Depends(_require_self_or_usage_admin),
    reporting: UsageReader = Depends(get_usage),
) -> DailyUsageResponse:
    """Return inclusive usage days, defaulting to thirty days ending today."""
    start_date, end_date = _parse_dates(filters.start, filters.end)
    try:
        return await reporting.fetch_daily_usage(user_id, start_date, end_date, filters)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except UsageUnavailable as error:
        raise _usage_unavailable(error) from error


@aggregate_router.get("/daily", response_model=DailyUsageResponse)
async def get_all_daily_usage(
    filters: Annotated[UsageQuery, Query()],
    _: None = Depends(require_role("langfuse-admin")),
    reporting: UsageReader = Depends(get_usage),
) -> DailyUsageResponse:
    """Aggregate daily model usage; only usage admins may omit the user filter."""
    start_date, end_date = _parse_dates(filters.start, filters.end)
    try:
        return await reporting.fetch_all_daily_usage(start_date, end_date, filters)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except UsageUnavailable as error:
        raise _usage_unavailable(error) from error


@aggregate_router.get("/people", response_model=UsagePeopleResponse)
async def get_usage_people(
    filters: Annotated[UsageQuery, Query()],
    _: None = Depends(require_role("langfuse-admin")),
    reporting: UsageReader = Depends(get_usage),
) -> UsagePeopleResponse:
    """List only active attributed principals for the admin picker and chart."""
    start_date, end_date = _parse_dates(filters.start, filters.end)
    try:
        return await reporting.fetch_user_breakdown(start_date, end_date, filters)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except UsageUnavailable as error:
        raise _usage_unavailable(error) from error


@router.get("/{user_id}/usage/sources", response_model=UsageSourcesResponse)
async def get_user_usage_sources(
    user_id: str,
    request: Request,
    filters: Annotated[UsageQuery, Query()],
    _: None = Depends(_require_self_or_usage_admin),
    reporting: UsageReader = Depends(get_usage),
) -> UsageSourcesResponse:
    """Return a user's originating apps and platform key totals, never key secrets."""
    result = await _source_breakdown(reporting, user_id, filters)
    await resolve_usage_key_names(result, request)
    return result


@aggregate_router.get("/sources", response_model=UsageSourcesResponse)
async def get_all_usage_sources(
    request: Request,
    filters: Annotated[UsageQuery, Query()],
    _: None = Depends(require_role("langfuse-admin")),
    reporting: UsageReader = Depends(get_usage),
) -> UsageSourcesResponse:
    """Only usage admins may aggregate origins and keys across principals."""
    result = await _source_breakdown(reporting, None, filters)
    await resolve_usage_key_names(result, request)
    return result


async def _source_breakdown(
    reporting: UsageReader, user_id: str | None, filters: UsageQuery
) -> UsageSourcesResponse:
    start, end = _parse_dates(filters.start, filters.end)
    try:
        return await reporting.fetch_source_breakdown(user_id, start, end, filters)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except UsageUnavailable as error:
        raise _usage_unavailable(error) from error


@router.get("/{user_id}/usage", response_model=UsageResponse)
async def get_user_usage(
    user_id: str,
    filters: Annotated[UsageFilters, Query()],
    _: None = Depends(_require_self_or_usage_admin),
    reporting: UsageReader = Depends(get_usage),
) -> UsageResponse:
    """Return call, token, and cost usage for one Keycloak user UUID."""
    try:
        return await reporting.fetch_usage(user_id, filters)
    except InvalidUsageRangeError as error:
        raise _invalid_range(error) from error
    except UsageUnavailable as error:
        raise _usage_unavailable(error) from error
