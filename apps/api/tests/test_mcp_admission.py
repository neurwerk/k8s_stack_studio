"""Restricted integration admission is independent of administrator and invocation grants."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from k8s_stack_studio import mcp_store
from k8s_stack_studio.controllers import gateway, mcp, mcp_setup
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.mcp_admission import admitted
from k8s_stack_studio.lib.mcp_publication import publication_snapshot
from k8s_stack_studio.models.mcp import McpRegistration
from tests.test_gateway import catalog, status
from tests.test_mcp_setup import principal, setup_projection


@pytest.fixture
def restricted(tmp_path):
    settings = publication_snapshot(setup_projection(tmp_path, "postgresql://localhost/test"))[0]
    items = [
        item.model_copy(update={"required_roles": ["glitchtip-admin", "security-reviewer"]})
        if item.id == "github"
        else item
        for item in settings.mcp_catalog
    ]
    return settings.model_copy(
        update={"mcp_catalog": items, "mcp_gateway_url": "https://gateway.example.test"}
    )


@pytest.mark.parametrize("roles", [set(), {"glitchtip-admin"}, {"security-reviewer"}])
async def test_nonmembers_cannot_read_or_mutate_restricted_integration(
    restricted, roles, monkeypatch
):
    """Even existing platform grants and administrator roles cannot bypass all-of admission."""
    caller = principal(
        roles={"studio-user", "mcp-admin", "gateway-admin", "platform-admin"} | roles
    )
    setups = AsyncMock(return_value={})
    begin = AsyncMock()
    monkeypatch.setattr(mcp_store, "setups", setups)
    monkeypatch.setattr(mcp_store, "begin", begin)
    app = FastAPI()
    app.include_router(mcp.router)
    app.include_router(mcp_setup.router)
    app.add_middleware(StudioAdmissionMiddleware)
    app.dependency_overrides[get_settings] = lambda: restricted
    app.dependency_overrides[mcp._live_settings] = lambda: restricted
    app.dependency_overrides[mcp_setup._configuration] = lambda: restricted

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = caller
        request.state.mcp_publication = {}
        return await call_next(request)

    def forbidden_native(request):
        pytest.fail("Denied integration must not contact ContextForge")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden_native)) as native:
        app.state.contextforge_admin_client = native
        app.state.contextforge_oauth_client = native
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={"origin": restricted.contextforge_oauth_studio_origin},
        ) as client:
            assert {item["id"] for item in (await client.get("/api/me/mcp/catalog")).json()} == {
                "context7",
                "brave",
            }
            assert {item["id"] for item in (await client.get("/api/admin/mcp")).json()} == {
                "context7",
                "brave",
            }
            assert (await client.get("/api/me/mcp/connections")).json() == {}
            for path in [
                "/api/me/mcp/github/status",
                "/api/me/mcp/github/publication",
                "/api/admin/mcp/github/tools",
            ]:
                assert (await client.get(path)).status_code == 404
            body = {"revision": 0, "operation_id": str(uuid4())}
            for path, payload in [
                ("/api/me/mcp/github/connect", {}),
                ("/api/me/mcp/github/tools", {}),
                ("/api/me/mcp/github/checks/0", {}),
                ("/api/admin/mcp/github/publish", body | {"selected_tools": []}),
                ("/api/admin/mcp/github/disable", body),
                ("/api/admin/mcp/github/refresh", body),
            ]:
                assert (await client.post(path, json=payload)).status_code == 404, path
            # Legacy discovery is separately gated even when setup is not enabled.
            restricted.mcp_setup_enabled = False
            assert (await client.post("/api/me/mcp/github/discover", json={})).status_code == 404
    begin.assert_not_awaited()


def test_all_roles_are_additive_and_empty_roles_preserve_existing_behavior(restricted):
    item = restricted.mcp_catalog[-1]
    caller = principal(roles={"studio-user", "glitchtip-admin", "security-reviewer"})
    assert admitted(item, caller)
    assert mcp._connection_admission(item.id, caller, restricted)[0] == item
    without_grants = replace(caller, agentgateway_roles=frozenset())
    with pytest.raises(HTTPException) as denied:
        mcp._connection_admission(item.id, without_grants, restricted)
    assert denied.value.status_code == 403
    assert not admitted(item, replace(caller, roles=frozenset({"studio-user"})))
    assert admitted(restricted.mcp_catalog[0], principal(roles={"studio-user"}))
    for invalid in [[""], ["glitchtip-admin", "glitchtip-admin"], [" glitchtip-admin"]]:
        with pytest.raises(ValueError):
            McpRegistration.model_validate(item.model_dump() | {"required_roles": invalid})


def test_publication_reconstruction_keeps_trusted_admission(restricted):
    data = Path(restricted.contextforge_publication_status_path).parent
    (data / "studio.json").write_text(
        json.dumps([item.model_dump() for item in restricted.mcp_catalog])
    )
    live, _ = publication_snapshot(restricted)
    assert live.mcp_catalog[-1].required_roles == ["glitchtip-admin", "security-reviewer"]


@pytest.mark.parametrize(
    ("live_roles", "caller_roles"),
    [
        ([], {"glitchtip-admin"}),
        (["glitchtip-admin"], {"glitchtip-admin"}),
        (["new-live-restriction"], {"glitchtip-admin", "security-reviewer"}),
    ],
    ids=["empty-live-policy", "weaker-live-policy", "additional-live-requirement"],
)
async def test_valid_publication_cannot_weaken_personal_or_setup_admission(
    restricted, live_roles, caller_roles, monkeypatch
):
    projection = Path(restricted.contextforge_publication_status_path).parent
    catalog = [
        item.model_dump() | {"required_roles": live_roles}
        if item.id == "github"
        else item.model_dump()
        for item in restricted.mcp_catalog
    ]
    (projection / "studio.json").write_text(json.dumps(catalog))
    caller = principal(roles={"studio-user", "mcp-admin", "gateway-admin"} | caller_roles)
    begin = AsyncMock(side_effect=AssertionError("Denied caller must not mutate setup storage"))
    monkeypatch.setattr(mcp_store, "begin", begin)
    monkeypatch.setattr(mcp_store, "setups", AsyncMock(return_value={}))
    app = FastAPI()
    app.include_router(mcp.router)
    app.include_router(mcp_setup.router)
    app.add_middleware(StudioAdmissionMiddleware)
    # Use the real reconstruction dependencies: neither _live_settings nor
    # _configuration may be replaced by a pre-authorized test settings object.
    app.dependency_overrides[get_settings] = lambda: restricted

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = caller
        return await call_next(request)

    calls = []

    def native(request):
        calls.append(request)
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(native)) as transport:
        app.state.contextforge_admin_client = transport
        app.state.contextforge_oauth_client = transport
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={"origin": restricted.contextforge_oauth_studio_origin},
        ) as client:
            for path in ("/api/me/mcp/catalog", "/api/admin/mcp"):
                response = await client.get(path)
                assert response.status_code == 200
                assert {item["id"] for item in response.json()} == {"context7", "brave"}
            assert (await client.get("/api/me/mcp/connections")).json() == {}
            for path in (
                "/api/me/mcp/github/status",
                "/api/me/mcp/github/publication",
                "/api/admin/mcp/github/tools",
            ):
                assert (await client.get(path)).status_code == 404, path
            body = {"revision": 0, "operation_id": str(uuid4())}
            for path, payload in (
                ("/api/me/mcp/github/connect", {}),
                ("/api/me/mcp/github/tools", {}),
                ("/api/me/mcp/github/checks/0", {}),
                ("/api/admin/mcp/github/publish", body | {"selected_tools": []}),
                ("/api/admin/mcp/github/disable", body),
                ("/api/admin/mcp/github/refresh", body),
            ):
                assert (await client.post(path, json=payload)).status_code == 404, path
            restricted.mcp_setup_enabled = False
            assert (await client.post("/api/me/mcp/github/discover", json={})).status_code == 404
    assert calls == []
    begin.assert_not_awaited()


@pytest.mark.parametrize(
    (
        "configured_roles",
        "live_roles",
        "omitted_error",
        "generic_visible",
        "member_visible",
        "caller_roles",
    ),
    [
        (
            ["glitchtip-admin", "security-reviewer"],
            ["glitchtip-admin"],
            False,
            False,
            True,
            {"glitchtip-admin"},
        ),
        (["glitchtip-admin"], None, True, False, True, set()),
        (["glitchtip-admin"], [], False, False, True, set()),
        ([], ["glitchtip-admin"], False, False, True, set()),
        (None, ["glitchtip-admin"], False, False, True, set()),
        (None, None, False, False, False, set()),
        (None, None, True, False, False, set()),
        ([], [], False, True, True, set()),
        ([], None, True, True, True, set()),
    ],
    ids=[
        "combined-policy",
        "failed-registration-omitted",
        "live-policy-cannot-weaken-configured",
        "live-policy-adds-restriction",
        "publication-before-configured-policy",
        "gateway-before-policy",
        "unknown-error-policy",
        "intentionally-unrestricted",
        "unrestricted-registration-omitted",
    ],
)
async def test_gateway_admin_cannot_discover_restricted_routes_or_health(
    restricted,
    tmp_path,
    configured_roles,
    live_roles,
    omitted_error,
    generic_visible,
    member_visible,
    caller_roles,
):
    projection = Path(restricted.contextforge_publication_status_path).parent
    configured_catalog = [
        item.model_copy(update={"required_roles": configured_roles})
        if item.id == "github"
        else item
        for item in restricted.mcp_catalog
        if item.id != "github" or configured_roles is not None
    ]
    live_catalog = [
        item.model_dump() | {"required_roles": live_roles}
        if item.id == "github"
        else item.model_dump()
        for item in restricted.mcp_catalog
        if item.id != "github" or live_roles is not None
    ]
    (projection / "studio.json").write_text(json.dumps(live_catalog))
    publication_path = projection / "publication.json"
    publication = json.loads(publication_path.read_text())
    if live_roles is None:
        if omitted_error:
            publication["integrations"][-1].update(state="error", error_code="verification-failed")
        else:
            publication["integrations"] = [
                item for item in publication["integrations"] if item["id"] != "github"
            ]
    publication_path.write_text(json.dumps(publication))
    tmp_path = tmp_path / "gateway"
    tmp_path.mkdir()
    data = catalog()
    entries = data.pop("external-subscription-providers")
    data["external-subscription-providers"] = []
    data["mcp-servers"] = entries
    for entry, identity in zip(entries, ("context7", "github"), strict=True):
        entry["destinations"][0].update(
            id=identity, kind="mcp", required_permissions=["llm:invoke", f"mcp:{identity}:invoke"]
        )
    (tmp_path / "gateway-catalog.json").write_text(json.dumps(data))
    (tmp_path / "gateway-status.json").write_text(json.dumps(status()))
    settings = restricted.model_copy(
        update={
            "gateway_catalog_file": str(tmp_path / "gateway-catalog.json"),
            "gateway_status_file": str(tmp_path / "gateway-status.json"),
            "mcp_catalog": configured_catalog,
        }
    )
    # These are valid snapshots, including errors with no runtime registration.
    assert {item.id for item in publication_snapshot(settings)[0].mcp_catalog} == {
        item["id"] for item in live_catalog
    }
    app = FastAPI()
    app.include_router(gateway.router)
    app.add_middleware(StudioAdmissionMiddleware)
    app.dependency_overrides[get_settings] = lambda: settings
    caller = principal(roles={"studio-user", "gateway-admin"} | caller_roles)

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = caller
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for path in ("/api/admin/gateway", "/api/gateway"):
            response = await client.get(path)
            assert response.status_code == 200
            assert ("hidden" in response.text) == generic_visible
            assert "context7" in response.text
        caller = principal(
            roles={"studio-user", "gateway-admin", "glitchtip-admin", "security-reviewer"}
        )
        for path in ("/api/admin/gateway", "/api/gateway"):
            response = await client.get(path)
            assert response.status_code == 200
            assert ("hidden" in response.text) == member_visible
            assert ("github" in response.text) == member_visible
        # Filtering never rewrites the effective operator-owned routing document.
        assert json.loads((tmp_path / "gateway-catalog.json").read_text()) == data
