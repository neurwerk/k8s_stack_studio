"""API key management routes — proxy to keycloak-api-key-bridge.

Endpoints:
   - GET    /api/users/{user_id}/agentgateway-permissions — list current grants
   - GET    /api/users/{user_id}/api-keys                  — list keys
   - POST   /api/users/{user_id}/api-keys                  — create key
   - POST   /api/users/{user_id}/api-keys/{key_id}/revoke  — revoke key

All endpoints forward the caller's JWT. Access is self-only unless the
caller has the ``api-key-admin`` role.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.dependencies import (
    get_current_user_id,
    get_settings,
    require_role,
)
from k8s_stack_studio.models.api_keys import CreateApiKeyRequest

router = APIRouter(prefix="/api/users", tags=["api-keys"])


async def _proxy_to_bridge(
    method: str,
    path: str,
    request: Request,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    """Forward a request to the keycloak-api-key-bridge service.

    Args:
        method: HTTP method (GET, POST).
        path: Path on the bridge (e.g. ``/api_keys?user_id=...``).
        request: The incoming FastAPI request (for the app state client).
        body: Optional JSON body for POST requests.

    Returns:
        The JSON response body from the bridge.
    """
    settings: Settings = get_settings()
    bridge_base = settings.keycloak_api_key_bridge_url.rstrip("/")
    url = f"{bridge_base}/{path.lstrip('/')}"

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }

    # This header was already verified by the Keycloak middleware.
    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        headers["Authorization"] = auth_header

    client: httpx.AsyncClient = request.app.state.http_client

    try:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=body or {})
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported method: {method}")
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="API key bridge unreachable",
        ) from exc

    if resp.status_code >= 400:
        detail = await _extract_detail(resp)
        raise HTTPException(status_code=resp.status_code, detail=detail)

    result: dict[str, Any] | list[Any] = resp.json()
    return result


async def _extract_detail(resp: httpx.Response) -> str:
    """Try to extract a detail message from an error response."""
    try:
        body: dict[str, Any] = resp.json()
        return str(body.get("detail", body.get("message", resp.reason_phrase)))
    except (ValueError, AttributeError):
        return resp.reason_phrase or f"Bridge error {resp.status_code}"


async def _bridge_response(
    method: str,
    path: str,
    request: Request,
    *,
    params: dict[str, str] | None = None,
) -> Response:
    """Forward a bridge response without changing its status, body, or content type."""
    settings: Settings = get_settings()
    url = f"{settings.keycloak_api_key_bridge_url.rstrip('/')}/{path.lstrip('/')}"
    auth_header = request.headers.get("Authorization", "")
    headers = {"Authorization": auth_header} if auth_header else {}
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        response = await client.request(method, url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="API key bridge unreachable",
        ) from exc
    content_type = response.headers.get("content-type")
    response_headers = {"content-type": content_type} if content_type else None
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response_headers,
    )


def _check_self_or_api_key_admin(
    user_id: str,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
) -> None:
    """Allow access if the caller is the target user or has api-key-admin role."""
    if user_id == current_user_id:
        return
    # Check api-key-admin role via the require_role dependency
    require_role("api-key-admin")(request)


# ── GET /api/users/{user_id}/api-keys ────────────────────────────────────────


@router.get("/{user_id}/agentgateway-permissions")
async def get_agentgateway_permissions(
    user_id: str,
    request: Request,
    _: None = Depends(_check_self_or_api_key_admin),
) -> Response:
    """Proxy the target user's AgentGateway grants without rewriting bridge output."""
    return await _bridge_response("GET", "permissions", request, params={"user_id": user_id})


@router.get("/{user_id}/api-keys")
async def list_api_keys(
    user_id: str,
    request: Request,
    _: None = Depends(_check_self_or_api_key_admin),
) -> dict[str, Any] | list[Any]:
    """List all API keys for the given user."""
    return await _proxy_to_bridge("GET", f"api_keys?user_id={user_id}", request)


# ── POST /api/users/{user_id}/api-keys ──────────────────────────────────────


@router.post("/{user_id}/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    user_id: str,
    request: Request,
    create_request: CreateApiKeyRequest,
    _: None = Depends(_check_self_or_api_key_admin),
) -> dict[str, Any] | list[Any]:
    """Create a new immutable, expiring API key for the given user."""
    body = create_request.model_dump() | {"target_user_id": user_id}
    return await _proxy_to_bridge(
        "POST",
        "api_keys",
        request,
        body=body,
    )


# ── POST /api/users/{user_id}/api-keys/{key_id}/revoke ──────────────────────


@router.post("/{user_id}/api-keys/{key_id}/revoke")
async def revoke_api_key(
    user_id: str,
    key_id: str,
    request: Request,
    _: None = Depends(_check_self_or_api_key_admin),
) -> dict[str, Any] | list[Any]:
    """Revoke an API key by ID."""
    return await _proxy_to_bridge(
        "POST",
        f"api_keys/{key_id}/revoke",
        request,
    )
