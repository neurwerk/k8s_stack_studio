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
NO_STORE = {"Cache-Control": "no-store"}


async def _permissions(request: Request, settings: Settings, binding_id: str) -> frozenset[str]:
    """Ask the Bridge to verify the original credential, not a caller's role header."""
    headers: dict[str, str] = {}
    dedicated = request.headers.getlist("x-neurwerk-authorization")
    if dedicated:
        if len(dedicated) != 1:
            raise HTTPException(401, "Invalid authentication credentials", headers=NO_STORE)
        headers["x-neurwerk-authorization"] = dedicated[0]
    else:
        bearer = request.headers.getlist("authorization")
        if len(bearer) != 1:
            raise HTTPException(401, "Missing authentication credentials", headers=NO_STORE)
        headers["authorization"] = bearer[0]
    if not settings.keycloak_api_key_bridge_url:
        raise HTTPException(503, "Gateway authentication unavailable", headers=NO_STORE)
    try:
        response = await request.app.state.http_client.post(
            f"{settings.keycloak_api_key_bridge_url.rstrip('/')}/gateway/caller-permissions",
            headers=headers,
            json={"binding_id": binding_id},
        )
    except httpx.HTTPError:
        raise HTTPException(503, "Gateway authentication unavailable", headers=NO_STORE) from None
    if response.status_code != 200:
        code = response.status_code if response.status_code in {401, 403} else 503
        raise HTTPException(code, "Gateway authentication failed", headers=NO_STORE)
    try:
        roles = response.json()["permissions"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, "Gateway authentication unavailable", headers=NO_STORE) from None
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise HTTPException(503, "Gateway authentication unavailable", headers=NO_STORE)
    return frozenset(role for role in roles if isinstance(role, str))


@router.get("/gateway/model-discovery/{binding_id}/models")
@router.get("/gateway/model-discovery/{binding_id}/models/{model:path}")
async def models(
    request: Request,
    binding_id: str,
    model: str | None = None,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Discover only models owned by the fixed, trusted route binding."""
    permissions = await _permissions(request, settings, binding_id)
    if "llm:invoke" not in permissions:
        raise HTTPException(403, "Model access denied", headers=NO_STORE)
    try:
        catalog = gateway_view(settings, permissions).catalog
    except GatewayUnavailableError:
        raise HTTPException(503, "Model catalog unavailable", headers=NO_STORE) from None
    entry = next(
        (
            entry
            for entry in catalog.self_hosted_api_providers + catalog.external_api_providers
            if entry.id == binding_id and any(route.entry_mode == "api" for route in entry.routes)
        ),
        None,
    )
    if entry is None:
        raise HTTPException(404, "Model not found", headers=NO_STORE)
    api_routes = {route.id for route in entry.routes if route.entry_mode == "api"}
    data = [
        {"id": item.id, "object": "model", "created": 0, "owned_by": "neurwerk"}
        for item in entry.destinations
        if item.kind == "model"
        and item.credential_modes
        and api_routes.intersection(item.endpoint_ids)
    ]
    if model is None:
        return JSONResponse({"object": "list", "data": data}, headers=NO_STORE)
    # Starlette has already decoded the path once; compare only the canonical ID.
    if model and not model.startswith("/"):
        for item in data:
            if item["id"] == model:
                return JSONResponse(item, headers=NO_STORE)
    raise HTTPException(404, "Model not found", headers=NO_STORE)
