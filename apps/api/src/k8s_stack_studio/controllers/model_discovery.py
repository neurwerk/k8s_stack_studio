"""OpenAI model discovery from the approved, permission-filtered gateway catalog."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.gateway import _entitled, gateway_catalog
from k8s_stack_studio.lib.gateway_files import GatewayUnavailableError

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}
logger = logging.getLogger(__name__)


async def _permissions(request: Request, settings: Settings, binding_id: str) -> frozenset[str]:
    """Verify gateway-normalized internal bearer identity through the Bridge."""
    for name in (
        "x-neurwerk-authorization",
        "x-neurwerk-credential-mode",
        "authorization-neurwerk",
        "x-api-key",
        "proxy-authorization",
    ):
        if name in request.headers:
            logger.warning("Ignored authentication header: %s", name)
    bearer = request.headers.getlist("authorization")
    if len(bearer) != 1 or "," in bearer[0]:
        if bearer:
            logger.warning("Ignored authentication header: authorization")
        raise HTTPException(401, "Missing authentication credentials", headers=NO_STORE)
    headers = {"authorization": bearer[0]}
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


@router.get("/gateway/model-discovery/{route_id}/models")
@router.get("/gateway/model-discovery/{route_id}/models/{model:path}")
async def models(
    request: Request,
    route_id: str,
    model: str | None = None,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """The gateway rewrite selects a fixed route, never a caller mode header."""
    try:
        catalog = gateway_catalog(settings)
    except GatewayUnavailableError:
        raise HTTPException(503, "Model catalog unavailable", headers=NO_STORE) from None
    entry = next(
        (
            entry
            for entry in catalog.self_hosted_api_providers
            + catalog.external_api_providers
            + catalog.external_subscription_providers
            if any(route.id == route_id and route.entry_mode == "api" for route in entry.routes)
        ),
        None,
    )
    if entry is None:
        raise HTTPException(404, "Model not found", headers=NO_STORE)
    permissions = await _permissions(request, settings, entry.id)
    if "llm:invoke" not in permissions:
        raise HTTPException(403, "Model access denied", headers=NO_STORE)
    route = next(route for route in entry.routes if route.id == route_id)
    selected = route.provider_credential_source
    permitted = _entitled(catalog, permissions)
    destinations = next(
        (
            item.destinations
            for entries in permitted.groups().values()
            for item in entries
            if item.id == entry.id
        ),
        [],
    )
    data = [
        {"id": item.id, "object": "model", "created": 0, "owned_by": "neurwerk"}
        for item in destinations
        if item.kind == "model"
        and any(mode.source == selected for mode in item.credential_modes)
        and (selected != "global" or entry.global_credential_status == "configured")
        and route_id in item.endpoint_ids
    ]
    if model is None:
        return JSONResponse({"object": "list", "data": data}, headers=NO_STORE)
    # Starlette has already decoded the path once; compare only the canonical ID.
    if model and not model.startswith("/"):
        for item in data:
            if item["id"] == model:
                return JSONResponse(item, headers=NO_STORE)
    raise HTTPException(404, "Model not found", headers=NO_STORE)
