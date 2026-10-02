"""Self-only, opt-in LLM activity search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel, Field

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.dependencies import get_current_user_id, get_settings
from k8s_stack_studio.lib.langfuse import Exchange, LangfuseClient, LangfuseReadError

router = APIRouter(prefix="/api/me/llm-activity", tags=["llm-activity"])


class SearchRequest(BaseModel):
    """Only display filters; never accept an upstream filter or owner ID."""

    model_config = {"extra": "forbid"}
    q: Annotated[str, Field(max_length=200)] = ""
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None


def _enabled(settings: Settings = Depends(get_settings)) -> Settings:
    """Deny reads before constructing or obtaining a Langfuse client."""
    if not settings.llm_logs_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    return settings


@router.post("", response_model=list[Exchange])
async def search_llm_activity(
    filters: SearchRequest,
    request: Request,
    response: Response,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(_enabled),
) -> list[Exchange]:
    """Return at most ten of this caller's exchanges; no trace-ID read route exists."""
    now = datetime.now(UTC)
    if (filters.start is None) != (filters.end is None):
        raise HTTPException(422, "Supply both From and To")
    start = filters.start.astimezone(UTC) if filters.start else now - timedelta(days=90)
    end = filters.end.astimezone(UTC) if filters.end else now + timedelta(seconds=1)
    if (
        start >= end
        or end - start > timedelta(days=90, seconds=1)
        or end > now + timedelta(seconds=1)
    ):
        raise HTTPException(422, "Choose an ascending time range of at most 90 days")
    client: httpx.AsyncClient = request.app.state.langfuse_client
    langfuse = LangfuseClient(
        settings.langfuse_url, settings.langfuse_public_key, settings.langfuse_secret_key, client
    )
    try:
        result = await langfuse.recent(user_id, start, end, filters.q.strip() or None)
    except LangfuseReadError as exc:
        raise HTTPException(502, "LLM activity is temporarily unavailable") from exc
    response.headers["Cache-Control"] = "no-store"
    return result
