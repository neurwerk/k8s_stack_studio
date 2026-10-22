"""Compose-only, non-forwarding gateway simulator with fixed synthetic responses.

Use a local Studio session token, never real provider credentials. This is not a
gateway implementation: API keys and real provider sessions are unsupported.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import ASGIApp, Receive, Scope, Send

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings
from k8s_stack_studio.lib.gateway import gateway_catalog
from k8s_stack_studio.models.gateway import GatewayDestination

Principal = Annotated[StudioPrincipal, Depends(get_current_principal)]
Configuration = Annotated[Settings, Depends(get_settings)]
PATHS = {
    "/local/api/v1": "local",
    "/openrouter/api/v1": "openrouter",
    "/openai/model/v1": "openai-model",
    "/openai/codex/v1/responses": "openai-codex",
    "/openai/api": "openai-web",
    **{f"/mcp/{name}": f"mcp-{name}" for name in ("brave", "context7", "github")},
}
SAMPLE = "Synthetic Studio gateway response. No provider request was sent."
# Public, harmless preview credentials; never use real keys or provider sessions.
# Send the API-key dummy on ordinary routes and the session dummy on Codex only.
SYNTHETIC_PROVIDER_API_KEY = "studio-demo-provider-key"
SYNTHETIC_CODEX_SESSION = "studio-demo-codex-session"
# Required fields and scalar types for this deliberately small, stateless preview.
TOOL_FIELDS: dict[str, tuple[tuple[str, ...], dict[str, str]]] = {
    "brave_web_search": (("query",), {"query": "string", "count": "integer"}),
    "brave_local_search": (("query",), {"query": "string", "count": "integer"}),
    "resolve-library-id": (("libraryName", "query"), {"libraryName": "string", "query": "string"}),
    "query-docs": (("libraryId", "query"), {"libraryId": "string", "query": "string"}),
    "get_me": ((), {}),
    "get_file_contents": (
        ("owner", "repo", "path"),
        {"owner": "string", "repo": "string", "path": "string", "ref": "string"},
    ),
    "search_repositories": (("query",), {"query": "string", "page": "integer"}),
}


def _tool_schema(tool: str) -> dict[str, object]:
    required, fields = TOOL_FIELDS[tool]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": {
            name: {"type": kind, "minLength" if kind == "string" else "minimum": 1}
            for name, kind in fields.items()
        },
    }


def _tool_arguments(tool: str, value: object) -> bool:
    """Apply exactly the required fields and scalar rules advertised by the preview."""
    required, fields = TOOL_FIELDS[tool]
    if (
        not isinstance(value, dict)
        or not set(required) <= value.keys()
        or not value.keys() <= fields.keys()
    ):
        return False
    return all(
        isinstance(item, str) and bool(item.strip())
        if fields[name] == "string"
        else type(item) is int and item >= 1
        for name, item in value.items()
    )


def _binding(path: str) -> str | None:
    return next(
        (
            identity
            for base, identity in PATHS.items()
            if path == base or path.startswith(base + "/")
        ),
        None,
    )


class PreviewIdentity:
    """Adapt only simulator headers before the real local JWT verifier runs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _binding(scope["path"]):
            headers = list(scope["headers"])
            platform = [value for key, value in headers if key == b"x-neurwerk-authorization"]
            origins = [value for key, value in headers if key == b"origin"]
            if origins and origins != [b"http://localhost:3001"]:
                await JSONResponse({"detail": "Local Studio origin required"}, status_code=403)(
                    scope, receive, send
                )
                return
            # Provider credentials are never passed to the verifier or retained.
            provider = [value for key, value in headers if key == b"authorization"]
            scope["preview_provider_supplied"] = bool(provider)
            dummy = (
                SYNTHETIC_CODEX_SESSION
                if _binding(scope["path"]) == "openai-codex"
                else SYNTHETIC_PROVIDER_API_KEY
            )
            scope["preview_provider_valid"] = len(provider) == 1 and provider[
                0
            ] == f"Bearer {dummy}".encode("ascii")
            scope["headers"] = [
                (key, value)
                for key, value in headers
                if key not in {b"authorization", b"x-neurwerk-authorization"}
            ]
            if len(platform) == 1:
                scope["headers"].append((b"authorization", platform[0]))
        await self.app(scope, receive, send)


def _destination(
    request: Request, principal: StudioPrincipal, settings: Settings, *, discovery: bool = False
) -> GatewayDestination:
    identity = _binding(request.url.path)
    entry = next(
        entry
        for entries in gateway_catalog(settings).groups().values()
        for entry in entries
        if entry.id == identity
    )
    destination = entry.destinations[0]
    if not set(destination.required_permissions) <= principal.agentgateway_roles:
        raise HTTPException(403, "Missing sample destination invocation permission")
    if discovery:
        if request.scope.get("preview_provider_supplied"):
            raise HTTPException(400, "Provider Authorization is not accepted for model discovery")
        if not any(
            set(mode.required_permissions) <= principal.agentgateway_roles
            and (
                mode.source != "company"
                or f"provider:{entry.provider_id}:company-use" in principal.agentgateway_roles
            )
            for mode in destination.credential_modes
        ):
            raise HTTPException(403, "No eligible sample credential mode")
        return destination
    if request.scope.get("preview_provider_supplied") and not request.scope.get(
        "preview_provider_valid"
    ):
        raise HTTPException(401, "Invalid synthetic provider credential")
    source = "caller_supplied" if request.scope.get("preview_provider_supplied") else "company"
    if any(mode.source == "none" for mode in destination.credential_modes):
        source = "none"
    mode = next((mode for mode in destination.credential_modes if mode.source == source), None)
    if mode is None:
        raise HTTPException(403, "Use a dummy provider Bearer value for this sample")
    if not set(mode.required_permissions) <= principal.agentgateway_roles:
        raise HTTPException(403, "Missing sample credential-mode permission")
    if source == "company":
        if f"provider:{entry.provider_id}:company-use" not in principal.agentgateway_roles:
            raise HTTPException(403, "Missing sample company-use permission")
        if entry.company_credential_status != "configured":
            raise HTTPException(409, "Sample company credential not configured")
    return destination


async def _body(request: Request) -> dict[str, object]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise HTTPException(413, "Sample request too large")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid sample JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Sample JSON object required")
    if body.get("stream") and request.url.path != "/openai/codex/v1/responses":
        raise HTTPException(400, "Streaming is not supported by the local simulator")
    return body


def _responses_input(value: object) -> bool:
    """Accept text or structured user text messages, without retaining either."""
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, list) or not value:
        return False
    for message in value:
        if not isinstance(message, dict) or message.get("role") != "user":
            return False
        content = message.get("content")
        if (
            not isinstance(content, list)
            or not content
            or any(
                not isinstance(part, dict)
                or part.get("type") != "input_text"
                or not isinstance(part.get("text"), str)
                or not part["text"].strip()
                for part in content
            )
        ):
            return False
    return True


routes = APIRouter()


@routes.get("/local/api/v1/models")
@routes.get("/openrouter/api/v1/models")
def models(request: Request, principal: Principal, settings: Configuration) -> dict[str, object]:
    destination = _destination(request, principal, settings, discovery=True)
    return {"object": "list", "data": [{"id": destination.model, "object": "model"}]}


@routes.get("/local/api/v1/models/{model:path}")
@routes.get("/openrouter/api/v1/models/{model:path}")
def model_details(
    model: str, request: Request, principal: Principal, settings: Configuration
) -> dict[str, object]:
    destination = _destination(request, principal, settings, discovery=True)
    if model != destination.model:
        raise HTTPException(403, "Model does not match this sample binding")
    return {"id": destination.model, "object": "model"}


@routes.post("/local/api/v1/chat/completions")
@routes.post("/openrouter/api/v1/chat/completions")
@routes.post("/openai/model/v1/responses")
@routes.post("/openai/codex/v1/responses")
async def model_response(
    request: Request, principal: Principal, settings: Configuration
) -> Response:
    destination = _destination(request, principal, settings)
    body = await _body(request)
    if body.get("model") != destination.model:
        raise HTTPException(403, "Model does not match this sample binding")
    if request.url.path in {"/openai/model/v1/responses", "/openai/codex/v1/responses"}:
        if not _responses_input(body.get("input")):
            raise HTTPException(
                400, "This sample requires nonempty text or user input_text messages"
            )
        result = {
            "id": "resp_studio_synthetic",
            "object": "response",
            "status": "completed",
            "model": destination.model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": SAMPLE}],
                }
            ],
        }
        if body.get("stream"):
            events = [
                {"type": "response.output_text.delta", "delta": SAMPLE},
                {"type": "response.completed", "response": result},
            ]
            return Response(
                "".join(f"data: {json.dumps(event)}\n\n" for event in events),
                media_type="text/event-stream",
            )
        return JSONResponse(result)
    messages = body.get("messages")
    if (
        not isinstance(messages, list)
        or not messages
        or any(
            not isinstance(message, dict)
            or message.get("role") != "user"
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
            for message in messages
        )
    ):
        raise HTTPException(400, "This sample requires user messages with nonempty text content")
    return JSONResponse(
        {
            "id": "chatcmpl-studio-synthetic",
            "object": "chat.completion",
            "created": 0,
            "model": destination.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": SAMPLE},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    )


@routes.get("/openai/api")
@routes.post("/openai/api")
def web_response(request: Request, principal: Principal, settings: Configuration) -> dict[str, str]:
    _destination(request, principal, settings)
    return {"mode": "synthetic", "message": SAMPLE}


@routes.post("/mcp/{integration}")
async def mcp_response(
    integration: str, request: Request, principal: Principal, settings: Configuration
) -> dict[str, object]:
    # Late import shares the exact in-memory publication/OAuth state, not a second copy.
    from mcp_preview import _available

    if integration not in {"brave", "context7", "github"}:
        raise HTTPException(404, "Unknown sample integration")
    _destination(request, principal, settings)
    item = _available(integration, principal)
    body = await _body(request)
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        raise HTTPException(400, "Sample JSON-RPC 2.0 request required")
    params = body.get("params", {})
    if not isinstance(params, dict):
        raise HTTPException(400, "Sample JSON-RPC params object required")
    identity = body.get("id")
    if type(identity) not in (str, int) or (isinstance(identity, str) and len(identity) > 128):
        raise HTTPException(400, "Bounded sample JSON-RPC id required")
    method = body.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "studio-synthetic", "version": "1"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {"name": name, "description": SAMPLE, "inputSchema": _tool_schema(name)}
                for name in item.approved_tools
            ]
        }
    elif method == "tools/call":
        tool = params.get("name")
        if not isinstance(tool, str) or tool not in item.approved_tools:
            raise HTTPException(403, "Tool is not approved for this sample")
        if not _tool_arguments(tool, params.get("arguments")):
            raise HTTPException(400, "Arguments do not match the synthetic tool input schema")
        result = {"content": [{"type": "text", "text": SAMPLE}], "isError": False}
    else:
        raise HTTPException(400, "Unsupported sample JSON-RPC method")
    return {"jsonrpc": "2.0", "id": identity, "result": result}


def install(app: FastAPI) -> None:
    """Install only in the mounted Compose entry point, never the release app."""
    app.include_router(routes)
    # Replace the production app's broad CORS in this local-only entry point.
    app.user_middleware = [item for item in app.user_middleware if item.cls is not CORSMiddleware]
    app.add_middleware(PreviewIdentity)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3001"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "X-Neurwerk-Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def no_store(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if _binding(request.url.path):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Studio-Gateway-Mode"] = "synthetic"
        return response
