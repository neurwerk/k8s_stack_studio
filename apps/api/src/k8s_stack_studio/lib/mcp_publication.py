"""Read one atomic, non-secret setup projection without caching stale readiness."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.mcp import McpPublicationStatus, McpRegistration


class PublicationUnavailableError(Exception):
    """A missing or inconsistent projection is unavailable, never stale ready."""


class _Integration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    state: str
    error_code: str | None


class _Publication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    checked_at: str
    integrations: list[_Integration] = Field(max_length=200)


def _read(directory: Path, name: str) -> str:
    path = directory / name
    if path.stat().st_size > 2_000_000:
        raise PublicationUnavailableError
    return path.read_text(encoding="utf-8")


def _statuses(publication: _Publication) -> dict[str, McpPublicationStatus]:
    statuses: dict[str, McpPublicationStatus] = {}
    for item in publication.integrations:
        if item.state not in {"pending-discovery", "published", "error"} or (
            item.error_code is not None
            and not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", item.error_code)
        ):
            raise PublicationUnavailableError
        status = McpPublicationStatus.model_validate(
            {
                "state": item.state,
                "checked_at": publication.checked_at,
                "error_code": item.error_code,
            }
        )
        if status.checked_at is None or status.checked_at.utcoffset() != timedelta(0):
            raise PublicationUnavailableError
        if (status.state == "error") != (status.error_code is not None):
            raise PublicationUnavailableError
        statuses[item.id] = status
    return statuses


def _binding(directory: Path, settings: Settings) -> str:
    fields = [
        ("team_id", "contextforge_team_id"),
        ("global_role_id", "contextforge_global_role_id"),
        ("team_role_id", "contextforge_team_role_id"),
    ]
    for key, field in fields:
        value = _read(directory, key).strip()
        if not value or value != getattr(settings, field):
            raise PublicationUnavailableError
    if not settings.contextforge_operator_discovery_enabled:
        return ""
    # These keys are deliberately absent after failed/disabled Base admission.
    for key, field in (
        ("operator_email", "contextforge_operator_email"),
        ("operator_subject", "contextforge_operator_subject"),
    ):
        if not (directory / key).exists() or _read(directory, key).strip() != getattr(
            settings, field
        ):
            return ""
    if not (directory / "operator_role_id").exists():
        return ""
    role_id = _read(directory, "operator_role_id").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", role_id) or role_id in {
        settings.contextforge_global_role_id,
        settings.contextforge_team_role_id,
    }:
        return ""
    return role_id


def _snapshot(
    directory: Path, name: str, settings: Settings
) -> tuple[Settings, dict[str, McpPublicationStatus]]:
    publication = _Publication.model_validate_json(_read(directory, name))
    expected_hash = _read(directory, "catalog_hash")
    if (
        not re.fullmatch(r"[a-f0-9]{64}", expected_hash)
        or publication.catalog_hash != expected_hash
    ):
        raise PublicationUnavailableError
    catalog = TypeAdapter(list[McpRegistration]).validate_json(_read(directory, "studio.json"))
    ids = {item.id for item in catalog}
    if (
        len(catalog) > 200
        or len(ids) != len(catalog)
        or not ids <= {item.id for item in publication.integrations}
        or len(publication.integrations) != len({item.id for item in publication.integrations})
        or len({item.gateway_id for item in catalog}) != len(catalog)
        or len({item.server_id for item in catalog}) != len(catalog)
    ):
        raise PublicationUnavailableError
    statuses = _statuses(publication)
    if any(status.state != "error" for identity, status in statuses.items() if identity not in ids):
        raise PublicationUnavailableError
    for item in catalog:
        if statuses[item.id].state == "published" and set(item.tool_names) != set(
            item.approved_tools
        ):
            raise PublicationUnavailableError
        if statuses[item.id].state == "pending-discovery" and item.tool_names:
            raise PublicationUnavailableError
    # Re-run the normal configuration validators for live native mappings.
    live = Settings.model_validate(
        {
            **settings.model_dump(),
            "mcp_catalog": catalog,
            "contextforge_operator_role_id": _binding(directory, settings),
        }
    )
    return live, statuses


def publication_snapshot(settings: Settings) -> tuple[Settings, dict[str, McpPublicationStatus]]:
    """Resolve Kubernetes' ..data once so all sibling reads belong to one update."""
    if not settings.contextforge_publication_status_path:
        return settings, {}
    try:
        path = Path(settings.contextforge_publication_status_path)
        directory = path.parent
        if (directory / "..data").is_symlink():
            directory = (directory / "..data").resolve(strict=True)
        elif path.is_symlink():
            directory = path.resolve(strict=True).parent
        result = _snapshot(directory, path.name, settings)
    except (OSError, ValueError, ValidationError):
        raise PublicationUnavailableError from None
    else:
        return result
