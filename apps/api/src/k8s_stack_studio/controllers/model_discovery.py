"""OpenAI model discovery from the approved, permission-filtered gateway catalog."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.gateway import gateway_view
from k8s_stack_studio.lib.gateway_files import GatewayUnavailableError

router = APIRouter()


async def _permissions(request: Request, settings: Settings) -> frozenset[str]:
    """Ask the Bridge to verify the original credential, not a caller's role header."""
    headers: dict[str, str] = {}
    dedicated = request.headers.getlist("x-neurwerk-authorization")
    if dedicated:
        if len(dedicated) != 1:
            raise HTTPException(401, "Invalid authentication credentials")
        headers["x-neurwerk-authorization"] = dedicated[0]
    else:
        bearer = request.headers.getlist("authorization")
        if len(bearer) != 1:
            raise HTTPException(401, "Missing authentication credentials")
        headers["authorization"] = bearer[0]
    if not settings.keycloak_api_key_bridge_url:
        raise HTTPException(503, "Gateway authentication unavailable")
    try:
        response = await request.app.state.http_client.post(
            f"{settings.keycloak_api_key_bridge_url.rstrip('/')}/gateway/caller-permissions",
            headers=headers,
        )
    except httpx.HTTPError:
        raise HTTPException(503, "Gateway authentication unavailable") from None
    if response.status_code != 200:
        code = response.status_code if response.status_code in {401, 403} else 503
        raise HTTPException(code, "Gateway authentication failed")
    try:
        roles = response.json()["permissions"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, "Gateway authentication unavailable") from None
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise HTTPException(503, "Gateway authentication unavailable")
    return frozenset(role for role in roles if isinstance(role, str))


@router.get("/gateway/model-discovery")
@router.get("/gateway/model-discovery/{model:path}")
async def models(
    request: Request,
    model: str | None = None,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """List permitted local models or return one canonical model by ID."""
    permissions = await _permissions(request, settings)
    if "llm:invoke" not in permissions:
        raise HTTPException(403, "Model access denied")
    try:
        catalog = gateway_view(settings, permissions).catalog
    except GatewayUnavailableError:
        raise HTTPException(503, "Model catalog unavailable") from None
    local_endpoints = {
        endpoint.id
        for endpoint in catalog.endpoints
        if endpoint.id == "api-local" and endpoint.entry_mode == "api"
    }
    data = [
        {"id": item.id, "object": "model", "created": 0, "owned_by": "neurwerk"}
        for item in catalog.destinations
        if item.kind == "model"
        and local_endpoints.intersection(item.endpoint_ids)
        and item.credential_modes
    ]
    headers = {"Cache-Control": "no-store"}
    if model is None:
        return JSONResponse({"object": "list", "data": data}, headers=headers)
    # Starlette has already decoded the path once; compare only the canonical ID.
    if model and not model.startswith("/"):
        for item in data:
            if item["id"] == model:
                return JSONResponse(item, headers=headers)
    raise HTTPException(404, "Model not found", headers=headers)
