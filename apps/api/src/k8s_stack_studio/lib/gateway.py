"""Present Base's effective configuration using verified caller permissions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.gateway_files import (
    GatewayUnavailableError,
    projected_path,
    read_document,
)
from k8s_stack_studio.models.gateway import (
    EndpointObservation,
    GatewayCatalog,
    GatewayHealth,
    GatewayStatus,
    GatewayView,
    ProfileHealth,
)


def _entitled(catalog: GatewayCatalog, permissions: frozenset[str]) -> GatewayCatalog:
    groups = {}
    for name, entries in catalog.groups().items():
        filtered = []
        for entry in entries:
            destinations = [
                item.model_copy(
                    update={
                        "credential_modes": [
                            mode
                            for mode in item.credential_modes
                            if set(mode.required_permissions) <= permissions
                            and (
                                mode.source != "global"
                                or (
                                    item.provider_id is not None
                                    and f"provider:{item.provider_id}:global-use" in permissions
                                )
                            )
                        ]
                    }
                )
                for item in entry.destinations
                if set(item.required_permissions) <= permissions
            ]
            endpoints = {identity for item in destinations for identity in item.endpoint_ids}
            if destinations:
                filtered.append(
                    entry.model_copy(
                        update={
                            "destinations": destinations,
                            "routes": [route for route in entry.routes if route.id in endpoints],
                            "global_credential_status": entry.global_credential_status
                            if (
                                entry.provider_id is not None
                                and f"provider:{entry.provider_id}:global-use" in permissions
                            )
                            else None,
                        }
                    )
                )
        groups[name] = filtered
    profiles = {
        identity
        for entries in groups.values()
        for entry in entries
        for item in entry.destinations
        for identity in item.profile_ids
    }
    return catalog.model_copy(
        update={
            **groups,
            "profiles": [item for item in catalog.profiles if item.id in profiles],
        }
    )


def _health(
    catalog: GatewayCatalog, status: GatewayStatus | None, *, invalid: bool
) -> GatewayHealth:
    now = datetime.now(UTC)
    reason = None
    if status is None:
        reason = "invalid" if invalid else "missing"
    elif (
        status.catalog_revision != catalog.catalog_revision
        or status.applied_policy_revision != catalog.policy_revision
    ):
        reason = "mismatch"
    elif not status.observed_at <= now < status.valid_until:
        reason = "stale"
    endpoints = {item.id: item for item in status.endpoints} if status and not reason else {}
    profiles = {item.id: item for item in status.profiles} if status else {}
    return GatewayHealth(
        state="unknown" if reason else "current",
        reason=reason,
        catalog_revision=status.catalog_revision if status else None,
        applied_policy_revision=status.applied_policy_revision if status else None,
        observed_at=status.observed_at if status else None,
        valid_until=status.valid_until if status else None,
        endpoints=[
            endpoints.get(item.id, EndpointObservation(id=item.id, state="unknown"))
            for item in catalog.endpoints
        ],
        profiles=[
            ProfileHealth(
                id=item.id,
                revision=profiles[item.id].revision if item.id in profiles else None,
                state=profiles[item.id].state
                if (
                    not reason
                    and item.id in profiles
                    and profiles[item.id].revision == item.revision
                )
                else "unknown",
            )
            for item in catalog.profiles
        ],
        signers=[
            item.model_copy(update={"state": "unknown"})
            if (
                status.catalog_revision != catalog.catalog_revision
                or not status.observed_at <= now < status.valid_until
                or item.observed_at > now
                or item.not_after is None
                or item.not_after <= now
            )
            else item
            for item in status.signers
        ]
        if status
        else [],
    )


def gateway_catalog(
    settings: Settings, *, generations: dict[Path, Path] | None = None
) -> GatewayCatalog:
    """Read and validate the chart-owned catalog without depending on runtime health."""
    try:
        return GatewayCatalog.model_validate_json(
            read_document(
                projected_path(
                    settings.gateway_catalog_file, {} if generations is None else generations
                )
            )
        )
    except (OSError, ValueError, GatewayUnavailableError):
        raise GatewayUnavailableError from None


def gateway_view(
    settings: Settings, permissions: frozenset[str], *, administrator: bool = False
) -> GatewayView:
    """Read current configuration; missing health never hides usable configuration."""
    generations: dict[Path, Path] = {}
    catalog = gateway_catalog(settings, generations=generations)
    observed = None
    invalid = False
    if settings.gateway_status_file:
        try:
            observed = GatewayStatus.model_validate_json(
                read_document(projected_path(settings.gateway_status_file, generations))
            )
        except FileNotFoundError:
            pass
        except (OSError, ValueError, GatewayUnavailableError):
            invalid = True
    if not administrator:
        catalog = _entitled(catalog, permissions)
        if observed:
            observed = observed.model_copy(update={"signers": []})
    return GatewayView(catalog=catalog, status=_health(catalog, observed, invalid=invalid))
