"""Compose-only MCP preview; never imported by the released Studio images.

Other Studio APIs and the real Keycloak admission middleware remain unchanged.
No fake credentials or provider traffic are needed for local UI design.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings, require_role
from k8s_stack_studio.main import create_app as production_app
from k8s_stack_studio.models.mcp import McpCheck, McpRegistration

Principal = Annotated[StudioPrincipal, Depends(get_current_principal)]
INTEGRATIONS = (
    McpRegistration(
        id="context7",
        name="Context7",
        authentication_model="no-authentication",
        gateway_id="local-context7",
        server_id="local-context7-server",
        approved_tools=["resolve-library-id", "query-docs"],
        tool_names={
            "resolve-library-id": "context7_resolve-library-id",
            "query-docs": "context7_query-docs",
        },
        checks=[
            McpCheck(
                name="Find documentation",
                tool="resolve-library-id",
                arguments={"libraryName": "React", "query": "React hooks"},
            )
        ],
    ),
    McpRegistration(
        id="brave",
        name="Brave Search",
        authentication_model="shared-authentication",
        gateway_id="local-brave",
        server_id="local-brave-server",
        approved_tools=["brave_web_search", "brave_local_search"],
        tool_names={
            "brave_web_search": "brave_web_search",
            "brave_local_search": "brave_local_search",
        },
        checks=[
            McpCheck(
                name="Search the web",
                tool="brave_web_search",
                arguments={"query": "Studio MCP preview"},
            )
        ],
    ),
    McpRegistration(
        id="github",
        name="GitHub",
        authentication_model="individual-authentication",
        gateway_id="local-github",
        server_id="local-github-server",
        approved_tools=["get_me", "get_file_contents", "search_repositories"],
        tool_names={
            "get_me": "github_get_me",
            "get_file_contents": "github_get_file_contents",
            "search_repositories": "github_search_repositories",
        },
        checks=[McpCheck(name="Check your GitHub account", tool="get_me")],
    ),
)
MODELS = {item.id: item for item in INTEGRATIONS}
AUTH_LABELS = {"context7": "No provider sign-in", "brave": "Company-managed", "github": "Personal"}


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


class PreviewState:
    """In-memory samples reset when the local API restarts."""

    def __init__(self) -> None:
        """Start with three published integrations; personal login is per user."""
        self.publication = {item.id: "published" for item in INTEGRATIONS}
        self.checked_at = {item.id: _stamp() for item in INTEGRATIONS}
        self.connected: set[str] = set()
        self.unavailable: set[str] = set()
        self.check = {item.id: "passed" for item in INTEGRATIONS}
        self.popups: dict[str, str] = {}

    def connection(self, principal: StudioPrincipal) -> str:
        """Never share another user's sample personal connection."""
        if principal.subject in self.unavailable:
            return "status unavailable"
        return "connected" if principal.subject in self.connected else "connect required"


state = PreviewState()


class Scenario(BaseModel):
    """Administrator-selectable, non-secret preview states."""

    integration: Literal["context7", "brave", "github"]
    publication: Literal["published", "pending-discovery", "error", "unavailable"]
    check: Literal["passed", "failed", "unavailable"]
    connection: Literal["connected", "connect required", "status unavailable"] = "connected"


def _admit(principal: StudioPrincipal, integration: str) -> McpRegistration:
    item = MODELS.get(integration)
    if item is None:
        raise HTTPException(404, "Unknown sample integration")
    if not {"llm:invoke", f"mcp:{integration}:invoke"} <= principal.agentgateway_roles:
        raise HTTPException(403, "Missing approved MCP invocation permission")
    return item


def _publication(integration: str) -> dict[str, str | None]:
    published = state.publication[integration]
    return {
        "state": published,
        "checked_at": state.checked_at[integration],
        "error_code": "verification-failed" if published == "error" else None,
    }


mcp = APIRouter(prefix="/api/me/mcp", dependencies=[Depends(require_role("studio-user"))])


@mcp.get("/catalog")
def catalog(principal: Principal) -> list[dict[str, object]]:
    """Same safe UI catalog shape as the deployed endpoint."""
    return [
        {
            "id": item.id,
            "name": item.name,
            "authentication_model": item.authentication_model,
            "permitted": {"llm:invoke", f"mcp:{item.id}:invoke"} <= principal.agentgateway_roles,
            "connection_status": "status unavailable" if item.id == "github" else None,
            "can_discover": item.id == "github"
            and "mcp-admin" in principal.roles
            and "mcp:github:invoke" in principal.agentgateway_roles,
            "publication": _publication(item.id),
        }
        for item in INTEGRATIONS
    ]


@mcp.get("/connections")
def connections(principal: Principal) -> dict[str, dict[str, object]]:
    """Return only this caller's personal GitHub status."""
    if "mcp:github:invoke" not in principal.agentgateway_roles:
        return {}
    return {
        "github": {
            "status": state.connection(principal),
            "checked_at": _stamp(),
            "retry_after": None,
            "message": "Could not check the saved connection."
            if principal.subject in state.unavailable
            else None,
        }
    }


@mcp.get("/{integration}/status")
def status(integration: str, principal: Principal) -> dict[str, object]:
    """Verify personal status only for the personal integration."""
    _admit(principal, integration)
    if integration != "github":
        raise HTTPException(404, "No personal connection for this integration")
    return connections(principal)["github"]


@mcp.get("/{integration}/publication")
def publication(integration: str, principal: Principal) -> dict[str, str | None]:
    """Publish status is not personal connection state."""
    _admit(principal, integration)
    return _publication(integration)


@mcp.post("/{integration}/connect")
def connect(integration: str, request: Request, principal: Principal) -> dict[str, str]:
    """Open a one-time local popup; no external provider is contacted."""
    _admit(principal, integration)
    if integration != "github" or request.headers.get("origin") != "http://localhost:3001":
        raise HTTPException(403, "Local Studio origin and personal GitHub access required")
    ticket = secrets.token_urlsafe(32)
    state.popups[ticket] = principal.subject
    return {
        "authorization_url": f"http://localhost:4010/oauth/callback?ticket={ticket}",
        "callback_origin": "http://localhost:4010",
    }


@mcp.post("/{integration}/discover")
def discover(integration: str, request: Request, principal: Principal) -> dict[str, str]:
    """An administrator discovers with their own existing sample connection."""
    _admit(principal, integration)
    if (
        integration != "github"
        or "mcp-admin" not in principal.roles
        or request.headers.get("origin") != "http://localhost:3001"
    ):
        raise HTTPException(403, "MCP administrator and local Studio origin required")
    if state.connection(principal) != "connected":
        raise HTTPException(409, "Connect your own provider account first")
    state.publication[integration] = "pending-discovery"
    return {"discovered_at": _stamp()}


def _available(integration: str, principal: StudioPrincipal) -> McpRegistration:
    item = _admit(principal, integration)
    if state.publication[integration] != "published":
        raise HTTPException(409, "Tools not published")
    if integration == "github" and state.connection(principal) != "connected":
        raise HTTPException(403, "Personal connection required")
    return item


@mcp.post("/{integration}/tools")
def tools(integration: str, principal: Principal) -> list[dict[str, object]]:
    """Render the approved sample tools after their required admission."""
    item = _available(integration, principal)
    return [
        {
            "name": name,
            "description": (
                f"Local sample of {name.replace('_', ' ')}. No provider request is sent."
            ),
            "checks": {
                str(index): check.model_dump()
                for index, check in enumerate(item.checks)
                if check.tool == name
            },
        }
        for name in item.approved_tools
    ]


@mcp.post("/{integration}/checks/{check_id}")
def check(integration: str, check_id: int, principal: Principal) -> dict[str, object]:
    """Return bounded local results, including the configured failure examples."""
    item = _available(integration, principal)
    if check_id < 0 or check_id >= len(item.checks):
        raise HTTPException(404, "Unknown sample check")
    if state.check[integration] == "unavailable":
        raise HTTPException(502, "Sample provider temporarily unavailable")
    result = {
        "github": {"login": "developer-demo"},
        "brave": {"results": 3},
        "context7": {"library": "React"},
    }[integration]
    return {
        "status": state.check[integration],
        "checked_at": _stamp(),
        "result": json.dumps(result),
        "display_label": "Account" if integration == "github" else None,
        "display_value": "developer-demo" if integration == "github" else None,
    }


demo = APIRouter(prefix="/api/dev/mcp", dependencies=[Depends(require_role("mcp-admin"))])


@demo.get("/scenarios")
def scenarios(principal: Principal) -> dict[str, object]:
    """Show the local-only state switcher to the demo administrator."""
    return {
        "integrations": [
            {
                "id": item.id,
                "authentication": AUTH_LABELS[item.id],
                "publication": state.publication[item.id],
                "check": state.check[item.id],
            }
            for item in INTEGRATIONS
        ],
        "connection": state.connection(principal),
    }


@demo.post("/scenario")
def scenario(body: Scenario, principal: Principal) -> dict[str, object]:
    """Switch one preview state without touching another user's connection."""
    _admit(principal, body.integration)
    state.publication[body.integration] = body.publication
    state.check[body.integration] = body.check
    state.checked_at[body.integration] = _stamp()
    if body.integration == "github":
        state.connected.discard(principal.subject)
        state.unavailable.discard(principal.subject)
        if body.connection == "connected":
            state.connected.add(principal.subject)
        elif body.connection == "status unavailable":
            state.unavailable.add(principal.subject)
    return scenarios(principal)


@demo.post("/publish")
def publish(principal: Principal) -> dict[str, object]:
    """Simulate the independent setup Job after explicit discovery."""
    _admit(principal, "github")
    if state.publication["github"] != "pending-discovery":
        raise HTTPException(409, "Discover first")
    state.publication["github"] = "published"
    state.checked_at["github"] = _stamp()
    return scenarios(principal)


popup = APIRouter()


@popup.get("/oauth/callback", include_in_schema=False)
def callback(ticket: str) -> HTMLResponse:
    """Complete a one-use local popup and notify only the local Studio origin."""
    subject = state.popups.pop(ticket, None)
    if subject is None:
        raise HTTPException(400, "Invalid local connection")
    state.connected.add(subject)
    target = json.dumps("http://localhost:3001")
    return HTMLResponse(
        "<!doctype html><html><body><script>"
        f"if(window.opener){{window.opener.postMessage("
        f'{{"type":"oauth_callback","status":"success"}},{target});window.close();}}'
        "</script><p>Local sample provider connected. You can close this window.</p></body></html>",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; "
            "base-uri 'none'; frame-ancestors 'none'",
        },
    )


def create_app() -> FastAPI:
    """Replace MCP routes only in the explicitly selected dev server entry point."""
    app = production_app()
    settings = Settings().model_copy(
        update={
            "mcp_catalog_enabled": True,
            "mcp_connections_enabled": True,
            "mcp_catalog": list(INTEGRATIONS),
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    routes = APIRouter()
    routes.include_router(mcp)
    routes.include_router(demo)
    routes.include_router(popup)
    # Earlier routes take priority; neither release image contains this entry point.
    app.router.routes[:0] = routes.routes
    return app
