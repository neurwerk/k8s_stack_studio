"""Resolve only scoped usage IDs through the bridge's non-secret bulk contract."""

from __future__ import annotations

from typing import Literal

import httpx
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings
from k8s_stack_studio.models.usage import UsageSourcesResponse


class UsageKeyName(BaseModel):
    """Validate the bridge allowlist before attaching a current display name."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=255)
    user_id: str = Field(min_length=1, max_length=255)
    kind: Literal["personal", "managed"]
    name: str = Field(min_length=1, max_length=255)


async def resolve_usage_key_names(result: UsageSourcesResponse, request: Request) -> None:
    """Gracefully retain unavailable IDs on old bridges or metadata outages."""
    principal = get_current_principal(request)
    is_admin = "langfuse-admin" in principal.roles
    references = {
        (key.id, person.user_id, key.kind)
        for person in result.people
        for key in person.credentials
        if key.id is not None
        and person.user_id is not None
        and key.kind in ("personal", "managed")
        and (is_admin or (person.user_id == principal.subject and key.kind == "personal"))
    }
    enrichment = result.key_name_enrichment
    enrichment.eligible_keys = len(references)
    enrichment.limit_reached = len(references) > 5000
    settings = get_settings()
    if not settings.keycloak_api_key_bridge_url:
        enrichment.lookup_failed = bool(references)
        return
    names: dict[tuple[str, str, str], str] = {}
    looked_up: set[tuple[str, str, str]] = set()
    client: httpx.AsyncClient = request.app.state.http_client
    # Bound enrichment independently of analytics size. Unresolved keys keep their IDs.
    refs = sorted(references)[:5000]
    for offset in range(0, len(refs), 500):
        batch = refs[offset : offset + 500]
        try:
            response = await client.post(
                f"{settings.keycloak_api_key_bridge_url.rstrip('/')}/usage/key-metadata",
                headers={"Authorization": request.headers.get("Authorization", "")},
                json={
                    "keys": [
                        {"id": key_id, "user_id": owner, "kind": kind}
                        for key_id, owner, kind in batch
                    ]
                },
            )
            response.raise_for_status()
            entries = TypeAdapter(list[UsageKeyName]).validate_json(response.content)
        except (httpx.HTTPError, ValidationError, ValueError):
            enrichment.lookup_failed = True
            break
        requested = set(batch)
        looked_up.update(requested)
        for entry in entries:
            identity = (entry.id, entry.user_id, entry.kind)
            if identity in requested:
                names[identity] = entry.name
    enrichment.looked_up_keys = len(looked_up)
    enrichment.named_keys = len(names)
    for person in result.people:
        for key in person.credentials:
            if key.id is not None and person.user_id is not None and key.kind is not None:
                identity = (key.id, person.user_id, key.kind)
                key.name = names.get(identity)
                key.name_status = (
                    "resolved"
                    if key.name is not None
                    else "unavailable"
                    if identity in looked_up
                    else "not_looked_up"
                )
