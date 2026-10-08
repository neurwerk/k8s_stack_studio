"""Approved catalog and personal native OAuth, with platform admission kept separate."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.contextforge import (
    ContextForgeAccountClient,
    ContextForgeAccountError,
    ContextForgeAccountMissingError,
    ContextForgeRateLimitError,
)
from k8s_stack_studio.lib.contextforge_oauth import (
    ContextForgeDiscoveryBusyError,
    ContextForgeOAuthClient,
)
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings, require_role
from k8s_stack_studio.lib.mcp_gateway import (
    McpGatewayError,
    available_tools,
    gateway_client,
    run_check,
)
from k8s_stack_studio.lib.mcp_publication import PublicationUnavailableError, publication_snapshot
from k8s_stack_studio.models.mcp import (
    McpCatalogEntry,
    McpCheckResult,
    McpConnectionStatus,
    McpConnectResponse,
    McpDiscoverResponse,
    McpPublicationStatus,
    McpRegistration,
    McpTool,
)

router = APIRouter(
    prefix="/api/me/mcp", tags=["mcp"], dependencies=[Depends(require_role("studio-user"))]
)


class PrepareAccountRequest(BaseModel):
    """Onboarding accepts no caller-supplied identity, destination or grants."""

    model_config = ConfigDict(extra="forbid")


def _live_settings(request: Request, settings: Settings = Depends(get_settings)) -> Settings:
    try:
        live, publication = publication_snapshot(settings)
    except PublicationUnavailableError:
        raise HTTPException(
            status_code=502,
            detail="MCP publication status is unavailable",
            headers={"Cache-Control": "no-store"},
        ) from None
    request.state.mcp_publication = publication
    return live


def _named_operator(principal: StudioPrincipal, settings: Settings) -> bool:
    return (
        settings.contextforge_operator_discovery_enabled
        and principal.subject == settings.contextforge_operator_subject
        and principal.profile.get("email_verified") is True
        and isinstance(principal.profile.get("email"), str)
        and str(principal.profile["email"]).lower() == settings.contextforge_operator_email
    )


async def _check_caller(
    request: Request,
    principal: StudioPrincipal,
    settings: Settings,
    email: str,
    *,
    prepare: bool = False,
) -> None:
    client = ContextForgeAccountClient(settings, request.app.state.contextforge_admin_client)
    if (
        settings.contextforge_operator_discovery_enabled
        and email == settings.contextforge_operator_email
    ):
        if not _named_operator(principal, settings):
            raise HTTPException(status_code=403, detail="Approved MCP operator binding is required")
        await client.check_operator(email)
    elif prepare:
        await client.prepare_account(email)
    else:
        await client.check_account(email)


def _verified_email(principal: StudioPrincipal) -> str:
    email = principal.profile.get("email")
    if (
        not isinstance(email, str)
        or not email.isascii()
        or len(email) > 254
        or principal.profile.get("email_verified") is not True
        or not re.fullmatch(r"[^@\s/\\?#\x00-\x1f\x7f]+@[^@\s/\\?#\x00-\x1f\x7f]+", email)
    ):
        raise HTTPException(status_code=403, detail="A verified account email is required")
    return email.lower()


def _require_connections(settings: Settings = Depends(get_settings)) -> None:
    if not settings.mcp_connections_enabled:
        raise HTTPException(status_code=404, detail="Personal MCP connections are not enabled")


def _connection_admission(
    integration_id: str, principal: StudioPrincipal, settings: Settings
) -> tuple[McpRegistration, str]:
    item = next((item for item in settings.mcp_catalog if item.id == integration_id), None)
    if item is None or item.authentication_model != "individual-authentication":
        raise HTTPException(status_code=404, detail="Personal MCP connection is not available")
    if not {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles:
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    return item, _verified_email(principal)


def _native_unavailable(error: Exception | None = None) -> HTTPException:
    if isinstance(error, ContextForgeRateLimitError):
        return HTTPException(
            status_code=429,
            detail="Connection checks are temporarily rate limited",
            headers={"Cache-Control": "no-store", "Retry-After": str(error.retry_after)},
        )
    return HTTPException(
        status_code=502,
        detail="Native MCP connection is unavailable",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{integration_id}/connect", dependencies=[Depends(_require_connections)])
async def connect(
    integration_id: str,
    body: PrepareAccountRequest,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> McpConnectResponse:
    """Connect/reconnect only by user intent; never accept browser identity or destinations."""
    item, email = _connection_admission(integration_id, principal, settings)
    # Bearer-only Studio auth already prevents ambient-cookie CSRF; also require
    # the operator-approved browser origin for this state-changing OAuth action.
    if request.headers.get("origin") != settings.contextforge_oauth_studio_origin:
        raise HTTPException(status_code=403, detail="Approved Studio origin is required")
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(30):
            await _check_caller(request, principal, settings, email, prepare=True)
            authorization_url = await ContextForgeOAuthClient(
                settings, request.app.state.contextforge_oauth_client, email
            ).authorize(item)
    except (ContextForgeAccountError, TimeoutError) as exc:
        raise _native_unavailable(exc) from None
    callback = urlsplit(settings.contextforge_oauth_callback_url)
    return McpConnectResponse(
        authorization_url=authorization_url,
        callback_origin=f"{callback.scheme}://{callback.netloc}",
    )


@router.get("/{integration_id}/status", dependencies=[Depends(_require_connections)])
async def connection_status(
    integration_id: str,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> McpConnectionStatus:
    """Recheck account, fixed-team membership and grants without restoring revoked access."""
    item, email = _connection_admission(integration_id, principal, settings)
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(30):
            await _check_caller(request, principal, settings, email)
            return await ContextForgeOAuthClient(
                settings, request.app.state.contextforge_oauth_client, email
            ).status(item)
    except (ContextForgeAccountError, TimeoutError) as exc:
        raise _native_unavailable(exc) from None


@router.get("/connections", dependencies=[Depends(_require_connections)])
async def connection_statuses(
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> dict[str, McpConnectionStatus]:
    """Verify the caller once per refresh, then read permitted personal connections."""
    response.headers["Cache-Control"] = "no-store"
    items = [
        item
        for item in settings.mcp_catalog
        if item.authentication_model == "individual-authentication"
        and {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles
    ]
    if not items:
        return {}
    email = _verified_email(principal)
    try:
        async with asyncio.timeout(30):
            await _check_caller(request, principal, settings, email)
    except ContextForgeAccountMissingError:
        return {
            item.id: McpConnectionStatus(status="connect required", checked_at=datetime.now(UTC))
            for item in items
        }
    except (ContextForgeAccountError, TimeoutError) as exc:
        raise _native_unavailable(exc) from None
    semaphore = asyncio.Semaphore(4)

    async def read_status(item: McpRegistration) -> tuple[str, McpConnectionStatus]:
        try:
            async with semaphore, asyncio.timeout(15):
                status = await ContextForgeOAuthClient(
                    settings, request.app.state.contextforge_oauth_client, email
                ).status(item)
                status.checked_at = datetime.now(UTC)
        except ContextForgeRateLimitError as exc:
            status = McpConnectionStatus(
                status="status unavailable",
                retry_after=exc.retry_after,
                message="Connection checks are temporarily rate limited.",
            )
        except (ContextForgeAccountError, TimeoutError):
            status = McpConnectionStatus(
                status="status unavailable", message="Could not check the saved connection."
            )
        return item.id, status

    return dict(await asyncio.gather(*(read_status(item) for item in items)))


def _tool_admission(
    integration_id: str, principal: StudioPrincipal, settings: Settings
) -> McpRegistration:
    if not (
        settings.mcp_catalog_enabled
        and settings.mcp_gateway_url
        and settings.contextforge_account_onboarding_enabled
    ):
        raise HTTPException(status_code=404, detail="MCP checks are not enabled")
    item = next((item for item in settings.mcp_catalog if item.id == integration_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="MCP integration is not available")
    if not {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles:
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    return item


def _gateway_error(error: McpGatewayError) -> HTTPException:
    headers = {"Cache-Control": "no-store"}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    return HTTPException(status_code=error.status, detail=str(error), headers=headers)


async def _prepare_tool_caller(
    request: Request, principal: StudioPrincipal, settings: Settings
) -> str:
    # The middleware has already verified this bearer token. Forward only this
    # credential; the gateway independently verifies identity and invocation grants.
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A signed-in caller is required")
    try:
        async with asyncio.timeout(30):
            await _check_caller(
                request, principal, settings, _verified_email(principal), prepare=True
            )
    except (ContextForgeAccountError, TimeoutError) as exc:
        raise _native_unavailable(exc) from None
    return authorization


@router.post("/{integration_id}/tools")
async def list_tools(
    integration_id: str,
    body: PrepareAccountRequest,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> list[McpTool]:
    """User-requested discovery prepares their account, never uses an operator token."""
    response.headers["Cache-Control"] = "no-store"
    item = _tool_admission(integration_id, principal, settings)
    authorization = await _prepare_tool_caller(request, principal, settings)
    try:
        async with gateway_client(settings.mcp_gateway_url, item, authorization) as client:
            return await available_tools(client, item)
    except McpGatewayError as exc:
        raise _gateway_error(exc) from None


@router.post("/{integration_id}/checks/{check_id}")
async def check_tool(
    integration_id: str,
    check_id: int,
    body: PrepareAccountRequest,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> McpCheckResult:
    """Execute only the chart-selected tool and arguments; no browser tool inputs."""
    response.headers["Cache-Control"] = "no-store"
    item = _tool_admission(integration_id, principal, settings)
    if not 0 <= check_id < len(item.checks):
        raise HTTPException(status_code=404, detail="MCP check is not configured")
    authorization = await _prepare_tool_caller(request, principal, settings)
    try:
        async with gateway_client(settings.mcp_gateway_url, item, authorization) as client:
            return await run_check(client, item, item.checks[check_id])
    except McpGatewayError as exc:
        raise _gateway_error(exc) from None


@router.post("/account")
async def prepare_account(
    body: PrepareAccountRequest,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> dict[str, str]:
    """Prepare a native account only after verified Studio and MCP admission."""
    if not settings.contextforge_account_onboarding_enabled:
        raise HTTPException(status_code=404, detail="MCP account onboarding is not enabled")
    if not any(
        {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles
        for item in settings.mcp_catalog
    ):
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    email = _verified_email(principal)
    response.headers["Cache-Control"] = "no-store"
    try:
        async with asyncio.timeout(30):
            await _check_caller(request, principal, settings, email, prepare=True)
    except (ContextForgeAccountError, TimeoutError):
        raise HTTPException(
            status_code=502,
            detail="Native MCP account preparation is unavailable",
            headers={"Cache-Control": "no-store"},
        ) from None
    return {"status": "ready"}


@router.get("/catalog")
async def get_catalog(
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> list[McpCatalogEntry]:
    """Return only fixed operator labels and the verified caller's platform permission."""
    if not settings.mcp_catalog_enabled:
        raise HTTPException(status_code=404, detail="MCP catalog is not enabled")
    response.headers["Cache-Control"] = "no-store"
    return [
        McpCatalogEntry(
            id=item.id,
            name=item.name,
            authentication_model=item.authentication_model,
            permitted={"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles,
            can_discover=(
                _named_operator(principal, settings)
                and {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles
            ),
            publication=request.state.mcp_publication.get(item.id),
            connection_status=(
                "status unavailable"
                if item.authentication_model == "individual-authentication"
                else None
            ),
        )
        for item in settings.mcp_catalog
    ]


@router.get("/{integration_id}/publication")
async def publication_status(
    integration_id: str,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> McpPublicationStatus:
    """Polling is a read only; it never triggers discovery or a Kubernetes Job."""
    response.headers["Cache-Control"] = "no-store"
    if not settings.mcp_catalog_enabled or not settings.contextforge_publication_status_path:
        raise HTTPException(status_code=404, detail="MCP publication status is not enabled")
    item = next((item for item in settings.mcp_catalog if item.id == integration_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="MCP integration is not available")
    if not {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles:
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    try:
        _, statuses = publication_snapshot(settings)
        return statuses[integration_id]
    except PublicationUnavailableError:
        return McpPublicationStatus(state="unavailable")


@router.post("/{integration_id}/discover")
async def discover(
    integration_id: str,
    body: PrepareAccountRequest,
    request: Request,
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(_live_settings),
) -> McpDiscoverResponse:
    """Explicit operator-only discovery for one fixed approved catalog gateway."""
    response.headers["Cache-Control"] = "no-store"
    if not settings.contextforge_operator_discovery_enabled:
        raise HTTPException(status_code=404, detail="MCP operator discovery is not enabled")
    if not _named_operator(principal, settings):
        raise HTTPException(status_code=403, detail="Approved MCP operator binding is required")
    if request.headers.get("origin") != settings.contextforge_oauth_studio_origin:
        raise HTTPException(status_code=403, detail="Approved Studio origin is required")
    item = next((item for item in settings.mcp_catalog if item.id == integration_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="MCP integration is not available")
    if not {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles:
        raise HTTPException(status_code=403, detail="Missing approved MCP invocation permission")
    email = _verified_email(principal)
    try:
        async with asyncio.timeout(45):
            await _check_caller(request, principal, settings, email)
            await ContextForgeOAuthClient(
                settings, request.app.state.contextforge_oauth_client, email
            ).discover(item)
    except ContextForgeDiscoveryBusyError:
        raise HTTPException(
            status_code=409,
            detail="Discovery is already running for this integration",
            headers={"Cache-Control": "no-store"},
        ) from None
    except (ContextForgeAccountError, TimeoutError) as exc:
        raise _native_unavailable(exc) from None
    return McpDiscoverResponse(discovered_at=datetime.now(UTC))
