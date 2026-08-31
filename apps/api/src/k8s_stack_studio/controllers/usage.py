"""Per-user Langfuse token and cost usage routes."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from k8s_stack_studio.lib.dependencies import get_current_user_id, get_langfuse, require_role
from k8s_stack_studio.lib.langfuse import LangfuseClient
from k8s_stack_studio.models.usage import UsageResponse

router = APIRouter(prefix="/api/users", tags=["usage"])


async def _require_self_or_langfuse_admin(user_id: str, request: Request) -> None:
    """Allow a user to view self usage or a Langfuse admin to view any user."""
    if user_id == get_current_user_id(request):
        return
    require_role("langfuse-admin")(request)


@router.get("/{user_id}/usage", response_model=UsageResponse)
async def get_user_usage(
    user_id: str,
    _: None = Depends(_require_self_or_langfuse_admin),
    langfuse: LangfuseClient = Depends(get_langfuse),
) -> UsageResponse:
    """Return Langfuse token and cost usage for one Keycloak user UUID."""
    try:
        return await langfuse.fetch_usage(user_id)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Langfuse usage query failed: HTTP {e.response.status_code}",
        ) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Langfuse unreachable: {e}",
        ) from e
