"""Logs viewer routes — read-only search against OpenSearch.

Endpoints:
  - GET /api/logs — search pod logs (newest first, default last 100)

Requires the ``opensearch-admin`` Keycloak realm role. OpenSearch itself is
queried with the dedicated read-only ``studio-logs-read`` internal user; the
caller's JWT is only used for the role check.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from k8s_stack_studio.lib.dependencies import get_opensearch, require_role
from k8s_stack_studio.lib.opensearch import DEFAULT_INDEX, OpenSearchClient

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def search_logs(
    q: str | None = Query(None, description="OpenSearch query_string against the log field"),
    namespace: str | None = Query(None, description="Exact Kubernetes namespace filter"),
    pod: str | None = Query(None, description="Exact Kubernetes pod name filter"),
    size: int = Query(100, ge=1, le=1000, description="Max number of log entries"),
    index: str = Query(DEFAULT_INDEX, description="Index pattern to search"),
    _: None = Depends(require_role("opensearch-admin")),
    opensearch: OpenSearchClient = Depends(get_opensearch),
) -> dict[str, Any]:
    """Return the newest log entries matching the given filters."""
    try:
        return await opensearch.search_logs(
            q=q, namespace=namespace, pod=pod, size=size, index=index
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenSearch query failed: HTTP {e.response.status_code}",
        ) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenSearch unreachable: {e}",
        ) from e
