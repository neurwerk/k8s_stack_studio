"""Additional integration admission, independent of administration and invocation grants."""

from fastapi import HTTPException

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.mcp_publication import PublicationUnavailableError, publication_snapshot
from k8s_stack_studio.models.gateway import GatewayView
from k8s_stack_studio.models.mcp import McpRegistration


def admitted(item: McpRegistration, principal: StudioPrincipal) -> bool:
    """Require every configured role; no administrator bypass or saved-token exception."""
    return set(item.required_roles) <= principal.roles


def require_admission(item: McpRegistration, principal: StudioPrincipal) -> None:
    """Do not reveal a restricted integration to an unadmitted caller."""
    if not admitted(item, principal):
        raise HTTPException(status_code=404, detail="MCP integration is not available")


def filter_gateway(
    view: GatewayView, settings: Settings, principal: StudioPrincipal
) -> GatewayView:
    """Remove restricted destinations and their unreferenced metadata from presentation only."""
    if settings.contextforge_publication_status_path:
        try:
            settings = publication_snapshot(settings)[0]
        except PublicationUnavailableError:
            raise HTTPException(
                status_code=503, detail="MCP admission policy is unavailable"
            ) from None
    denied = {item.id for item in settings.mcp_catalog if not admitted(item, principal)}
    if not denied:
        return view
    entries = []
    for entry in view.catalog.mcp_servers:
        destinations = [item for item in entry.destinations if item.id not in denied]
        if destinations:
            endpoints = {identity for item in destinations for identity in item.endpoint_ids}
            entries.append(
                entry.model_copy(
                    update={
                        "destinations": destinations,
                        "routes": [route for route in entry.routes if route.id in endpoints],
                    }
                )
            )
    catalog = view.catalog.model_copy(update={"mcp_servers": entries})
    profiles = {identity for item in catalog.destinations for identity in item.profile_ids}
    catalog = catalog.model_copy(
        update={
            "profiles": [item for item in catalog.profiles if item.id in profiles],
        }
    )
    endpoints = {item.id for item in catalog.endpoints}
    return view.model_copy(
        update={
            "catalog": catalog,
            "status": view.status.model_copy(
                update={
                    "endpoints": [item for item in view.status.endpoints if item.id in endpoints],
                    "profiles": [item for item in view.status.profiles if item.id in profiles],
                }
            ),
        }
    )
