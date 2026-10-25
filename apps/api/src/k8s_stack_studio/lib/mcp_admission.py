"""Additional integration admission, independent of administration and invocation grants."""

from fastapi import HTTPException

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.models.gateway import GatewayView
from k8s_stack_studio.models.mcp import McpRegistration


def admission_requirements(
    configured: list[McpRegistration], live: list[McpRegistration]
) -> dict[str, set[str]]:
    """Union trusted policies without losing configured requirements or omitted identities."""
    requirements: dict[str, set[str]] = {}
    for item in (*configured, *live):
        requirements.setdefault(item.id, set()).update(item.required_roles)
    return requirements


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
    policies = admission_requirements(settings.mcp_catalog, [])
    managed = bool(settings.contextforge_publication_status_path)
    if managed:
        # Publication reconstruction shares the pure helper above; import the
        # snapshot reader here to keep that dependency free of an import cycle.
        from k8s_stack_studio.lib.mcp_publication import (
            PublicationUnavailableError,
            publication_snapshot,
        )

        try:
            live = publication_snapshot(settings)[0]
        except PublicationUnavailableError:
            raise HTTPException(
                status_code=503, detail="MCP admission policy is unavailable"
            ) from None
        # Registration readiness may omit an errored integration, and independent
        # projections can update in either order. Neither can remove configured
        # admission requirements; combine trusted policies conservatively.
        policies = admission_requirements(settings.mcp_catalog, live.mcp_catalog)
    denied = {
        item.id
        for entry in view.catalog.mcp_servers
        for item in entry.destinations
        if (managed and item.id not in policies)
        or not policies.get(item.id, set()) <= principal.roles
    }
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
