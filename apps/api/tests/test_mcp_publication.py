"""Current setup projections stay atomic, fail closed and preserve durable bindings."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from k8s_stack_studio import mcp_store
from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.mcp import _tool_admission
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.mcp_publication import (
    PublicationUnavailableError,
    personal_snapshot,
    publication_snapshot,
)
from k8s_stack_studio.models.mcp import McpPublicationStatus, McpRegistration

REGISTRATION = Path(__file__).parent / "fixtures/mcp-registration-before-cleanup.json"
# Captured on pre-cleanup main (4d97474), independently of the model under test.
PRE_CLEANUP_BINDING = "e254ca77625630e168e0b6af2221fe765894a0a6d42fe695cbd482da13460a81"


def configured_projection(tmp_path):
    catalog = [McpRegistration.model_validate_json(REGISTRATION.read_text())]
    settings = Settings(
        mcp_catalog_enabled=True,
        mcp_catalog=catalog,
        contextforge_team_id="fixed-team",
        contextforge_global_role_id="global-empty",
        contextforge_team_role_id="team-invoke",
        contextforge_account_onboarding_enabled=True,
        contextforge_service_auth_mode="trusted-proxy",
        contextforge_service_account_email="provisioner@example.test",
        contextforge_url="https://native.example.test",
        mcp_connections_enabled=True,
        contextforge_oauth_studio_origin="https://studio.example.test",
        contextforge_oauth_callback_url="https://studio.example.test/oauth/callback",
        contextforge_admin_discovery_enabled=True,
        contextforge_publication_status_path=str(tmp_path / "publication.json"),
        mcp_setup_enabled=True,
        notice_database_url="postgresql://synthetic@localhost/studio_test",
    )
    data = tmp_path / "generation-one"
    data.mkdir()
    (tmp_path / "..data").symlink_to(data, target_is_directory=True)
    contents = {
        "studio.json": json.dumps([item.model_dump() for item in catalog]),
        "catalog_hash": "a" * 64,
        "team_id": "fixed-team",
        "global_role_id": "global-empty",
        "team_role_id": "team-invoke",
        "setup_mode": "studio-v1",
        "admin_discovery_role_id": "admin-discovery",
        "admin_discovery_ready": "true",
        "publication.json": json.dumps(
            {
                "catalog_hash": "a" * 64,
                "checked_at": datetime.now(UTC).isoformat(),
                "integrations": [
                    {"id": "github", "state": "pending-discovery", "error_code": None}
                ],
            }
        ),
    }
    for name, value in contents.items():
        (data / name).write_text(value)
        (tmp_path / name).symlink_to(f"..data/{name}")
    return settings, data


def test_live_atomic_projection_and_fail_closed(tmp_path, monkeypatch):
    settings, _ = configured_projection(tmp_path)
    live, statuses = publication_snapshot(settings)
    assert live.contextforge_admin_discovery_role_id == "admin-discovery"
    assert statuses["github"].state == "pending-discovery"
    from k8s_stack_studio.lib import mcp_publication

    original = mcp_publication._read

    def switch(directory, name):
        if name == "publication.json":
            (tmp_path / "..data").unlink()
            (tmp_path / "..data").symlink_to(tmp_path / "missing-generation")
        return original(directory, name)

    monkeypatch.setattr(mcp_publication, "_read", switch)
    assert publication_snapshot(settings)[1]["github"].state == "pending-discovery"
    with pytest.raises(PublicationUnavailableError):
        publication_snapshot(settings)
    settings.contextforge_publication_status_path = ""
    settings.mcp_setup_enabled = False
    assert publication_snapshot(settings) == (settings, {})


def test_personal_tool_checks_require_live_publication(tmp_path):
    settings, _ = configured_projection(tmp_path)
    settings.mcp_gateway_url = "https://gateway.example.test"
    principal = StudioPrincipal(
        "reader",
        frozenset({"studio-user"}),
        frozenset({"llm:invoke", "mcp:github:invoke"}),
        {},
    )
    request = Request({"type": "http"})
    for state in ("pending-discovery", "error", "unavailable"):
        request.state.mcp_publication = {"github": McpPublicationStatus(state=state)}
        with pytest.raises(HTTPException) as denied:
            _tool_admission("github", principal, settings, request)
        assert denied.value.status_code == 404
    request.state.mcp_publication = {"github": McpPublicationStatus(state="published")}
    assert _tool_admission("github", principal, settings, request).id == "github"


@pytest.mark.parametrize(
    "key,value",
    [
        ("catalog_hash", "other"),
        ("catalog_hash", "b" * 64),
        ("checked_at", "2026-01-01T00:00:00"),
        ("integrations", [{"id": "other", "state": "published", "error_code": None}]),
    ],
)
def test_invalid_projection_is_not_stale_ready(tmp_path, key, value):
    settings, data = configured_projection(tmp_path)
    publication = json.loads((data / "publication.json").read_text())
    publication[key] = value
    (data / "publication.json").write_text(json.dumps(publication))
    with pytest.raises(PublicationUnavailableError):
        publication_snapshot(settings)


def test_empty_startup_and_omitted_unverified_registration(tmp_path):
    settings, data = configured_projection(tmp_path)
    settings = Settings.model_validate({**settings.model_dump(), "mcp_catalog": []})
    (data / "studio.json").write_text("[]")
    publication = json.loads((data / "publication.json").read_text())
    publication["integrations"][0].update(state="error", error_code="provider-unavailable")
    (data / "publication.json").write_text(json.dumps(publication))
    live, statuses = publication_snapshot(settings)
    assert live.mcp_catalog == [] and statuses["github"].state == "error"
    registration = McpRegistration.model_validate_json(REGISTRATION.read_text())
    (data / "studio.json").write_text(json.dumps([registration.model_dump()]))
    publication["integrations"][0].update(state="pending-discovery", error_code=None)
    (data / "publication.json").write_text(json.dumps(publication))
    assert publication_snapshot(settings)[0].mcp_catalog == [registration]


async def test_pre_cleanup_binding_keeps_saved_publication_usable(tmp_path, monkeypatch):
    settings, _ = configured_projection(tmp_path)
    item = settings.mcp_catalog[0]
    assert item.model_dump() == json.loads(REGISTRATION.read_text())
    assert mcp_store.binding(item) == PRE_CLEANUP_BINDING
    saved = {
        "binding": PRE_CLEANUP_BINDING,
        "enabled": True,
        "selected_tools": ["read"],
        "published_tools": {"read": "github_read"},
        "publication_uncertain": False,
        "revision": 7,
        "actor": "existing-owner",
        "published_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    read = AsyncMock(return_value={"github": saved.copy()})
    monkeypatch.setattr(mcp_store, "setups", read)
    live, statuses = await personal_snapshot(settings)
    assert statuses["github"].state == "published"
    assert live.mcp_catalog[0].approved_tools == ["read"]
    assert live.mcp_catalog[0].tool_names == {"read": "github_read"}
    assert mcp_store.binding(live.mcp_catalog[0]) == PRE_CLEANUP_BINDING
    assert read.return_value["github"] == saved
