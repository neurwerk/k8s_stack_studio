"""Gateway presentation must not turn configuration or admin access into entitlement."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.gateway import router
from k8s_stack_studio.lib import gateway
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.gateway_files import GatewayUnavailableError
from k8s_stack_studio.models.gateway import GatewayCatalog, GatewayStatus


def catalog():
    data: dict[str, Any] = {
        "schema_version": 2,
        "catalog_revision": "catalog-1",
        "policy_revision": "policy-1",
        "endpoints": [
            {
                "id": name,
                "url": f"https://{name}.example.test:8443",
                "entry_mode": "forward_proxy",
                "caller_auth_modes": ["proxy_basic"],
            }
            for name in ("visible", "hidden")
        ],
        "destinations": [
            {
                "id": name,
                "kind": "application",
                "display_name": name,
                "endpoint_ids": [name],
                "profile_ids": [name],
                "required_permissions": ["llm:invoke", f"application:{name}:invoke"],
                "credential_modes": [
                    {"source": "caller_supplied", "required_permissions": []},
                    {"source": "company", "required_permissions": ["provider:example:company-use"]},
                ],
            }
            for name in ("visible", "hidden")
        ],
        "profiles": [
            {
                "id": name,
                "revision": "profile-1",
                "limitations": ["Operation-specific support"],
                "operations": [
                    {
                        "id": "login",
                        "support": "supported",
                        "restoration_scope": "request",
                        "limitations": [],
                    },
                    {
                        "id": "upload",
                        "support": "unknown",
                        "restoration_scope": "none",
                        "limitations": ["Not qualified"],
                    },
                ],
            }
            for name in ("visible", "hidden")
        ],
    }
    routes = data.pop("endpoints")
    destinations = data.pop("destinations")
    data.update(
        {
            "self-hosted-api-providers": [],
            "external-api-providers": [],
            "mcp-servers": [],
            "external-subscription-providers": [
                {
                    "id": route["id"],
                    "display_name": route["id"],
                    "provider_id": None,
                    "routes": [route],
                    "destinations": [destination],
                }
                for route, destination in zip(routes, destinations, strict=True)
            ],
        }
    )
    return data


def status():
    now = datetime.now(UTC)
    return {
        "schema_version": 1,
        "catalog_revision": "catalog-1",
        "applied_policy_revision": "policy-1",
        "observed_at": (now - timedelta(seconds=10)).isoformat(),
        "valid_until": (now + timedelta(minutes=5)).isoformat(),
        "endpoints": [{"id": name, "state": "available"} for name in ("visible", "hidden")],
        "profiles": [
            {"id": name, "revision": "profile-1", "state": "available"}
            for name in ("visible", "hidden")
        ],
    }


@pytest.fixture
def projection(tmp_path):
    (tmp_path / "catalog.json").write_text(json.dumps(catalog()))
    (tmp_path / "status.json").write_text(json.dumps(status()))
    return Settings(
        gateway_catalog_file=str(tmp_path / "catalog.json"),
        gateway_status_file=str(tmp_path / "status.json"),
    )


def test_environment_path_contract(monkeypatch):
    monkeypatch.setenv("STUDIO_GATEWAY_CATALOG_FILE", "/public/catalog.json")
    monkeypatch.setenv("STUDIO_GATEWAY_STATUS_FILE", "/public/status.json")
    monkeypatch.setenv("STUDIO_GATEWAY_TRUST_FILE", "/trust/snapshots.json")
    settings = Settings()
    assert settings.gateway_catalog_file == "/public/catalog.json"
    assert settings.gateway_status_file == "/public/status.json"
    assert settings.gateway_trust_file == "/trust/snapshots.json"
    assert Settings.model_validate(settings.model_dump()) == settings


async def test_gateway_authorization_and_entitlement(projection):
    state = {"principal": None}
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(StudioAdmissionMiddleware)
    app.dependency_overrides[get_settings] = lambda: projection

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = state["principal"]
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        for path in ("/api/gateway", "/api/admin/gateway"):
            denied = await client.get(path)
            assert denied.status_code == 401
            assert denied.headers["cache-control"] == "no-store"
        state["principal"] = StudioPrincipal("self", frozenset({"gateway-admin"}), frozenset(), {})
        denied = await client.get("/api/admin/gateway")
        assert denied.status_code == 403
        assert denied.headers["cache-control"] == "no-store"
        state["principal"] = StudioPrincipal(
            "self",
            frozenset({"studio-user", "keycloak-admin", "langfuse-admin"}),
            frozenset({"llm:invoke", "application:visible:invoke"}),
            {},
        )
        assert (await client.get("/api/admin/gateway")).status_code == 403
        response = await client.get("/api/gateway?permissions=provider:example:company-use")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "hidden" not in response.text
        data = response.json()
        assert data["catalog"]["external-subscription-providers"][0]["destinations"][0][
            "credential_modes"
        ] == [{"source": "caller_supplied", "required_permissions": []}]
        assert data["status"]["endpoints"] == [{"id": "visible", "state": "available"}]
        assert data["catalog"]["profiles"][0]["operations"][1]["support"] == "unknown"
        state["principal"] = StudioPrincipal(
            "admin",
            frozenset({"studio-user", "gateway-admin"}),
            frozenset(),
            {},
        )
        response = await client.get("/api/admin/gateway")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        entries = response.json()["catalog"]["external-subscription-providers"]
        assert len(entries) == 2
        assert len(entries[0]["destinations"][0]["credential_modes"]) == 2
        personal = (await client.get("/api/gateway")).json()
        for key in (
            "self-hosted-api-providers",
            "external-api-providers",
            "external-subscription-providers",
            "mcp-servers",
            "profiles",
        ):
            assert personal["catalog"][key] == []
        assert personal["status"]["endpoints"] == personal["status"]["profiles"] == []


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"catalog_revision": "old"}, "mismatch"),
        ({"applied_policy_revision": "old"}, "mismatch"),
        ({"observed_at": "2020-01-01T00:00:00Z", "valid_until": "2020-01-02T00:00:00Z"}, "stale"),
        ({"observed_at": "2100-01-01T00:00:00Z", "valid_until": "2100-01-02T00:00:00Z"}, "stale"),
        ({"raw_diagnostic": "private-body"}, "invalid"),
        ({"schema_version": 2}, "invalid"),
    ],
)
def test_untrusted_observations_remain_unknown(projection, tmp_path, change, reason):
    (tmp_path / "status.json").write_text(json.dumps({**status(), **change}))
    view = gateway.gateway_view(projection, frozenset(), administrator=True)
    assert view.status.reason == reason
    assert {item.state for item in view.status.endpoints + view.status.profiles} == {"unknown"}
    assert "private-body" not in view.model_dump_json()
    if reason == "mismatch":
        assert "old" in view.status.model_dump_json()


def test_missing_and_partial_profile_evidence(projection, tmp_path):
    observed = status()
    observed["endpoints"] = []
    observed["profiles"][0]["revision"] = "old-profile"
    (tmp_path / "status.json").write_text(json.dumps(observed))
    view = gateway.gateway_view(projection, frozenset(), administrator=True)
    assert view.status.profiles[0].state == "unknown"
    assert view.status.profiles[0].revision == "old-profile"
    assert view.status.profiles[1].state == "available"
    assert all(item.state == "unknown" for item in view.status.endpoints)
    (tmp_path / "status.json").unlink()
    view = gateway.gateway_view(projection, frozenset(), administrator=True)
    assert view.status.reason == "missing"
    assert all(item.state == "unknown" for item in view.status.profiles)


def test_unknown_revision_preserves_fresh_admin_signer_evidence(projection, tmp_path):
    observed = status()
    observed["applied_policy_revision"] = None
    observed["signers"] = [
        {
            "pod_uid": "replica-uid",
            "pod_name": "gateway-replica",
            "listener": "inspect-example",
            "state": "verified",
            "observed_at": observed["observed_at"],
            "fingerprint_sha256": "a" * 64,
            "not_after": observed["valid_until"],
        }
    ]
    (tmp_path / "status.json").write_text(json.dumps(observed))
    view = gateway.gateway_view(projection, frozenset(), administrator=True)
    assert view.status.state == "unknown"
    assert view.status.applied_policy_revision is None
    assert view.status.signers[0].state == "verified"
    assert gateway.gateway_view(projection, frozenset()).status.signers == []
    observed["observed_at"] = "2020-01-01T00:00:00Z"
    observed["valid_until"] = "2020-01-02T00:00:00Z"
    observed["signers"][0]["observed_at"] = observed["observed_at"]
    (tmp_path / "status.json").write_text(json.dumps(observed))
    assert (
        gateway.gateway_view(projection, frozenset(), administrator=True).status.signers[0].state
        == "unknown"
    )


def test_catalog_and_status_share_projected_generation(tmp_path, monkeypatch):
    for generation in ("old", "new"):
        directory = tmp_path / generation
        directory.mkdir()
        (directory / "catalog.json").write_text(json.dumps(catalog()))
        observed = status()
        if generation == "new":
            observed["applied_policy_revision"] = "policy-2"
        (directory / "status.json").write_text(json.dumps(observed))
    pointer = tmp_path / "..data"
    pointer.symlink_to(tmp_path / "old")
    original = gateway.read_document

    def rotate_after_catalog(path):
        result = original(path)
        if path.name == "catalog.json":
            pointer.unlink()
            pointer.symlink_to(tmp_path / "new")
        return result

    monkeypatch.setattr(gateway, "read_document", rotate_after_catalog)
    settings = Settings(
        gateway_catalog_file=str(tmp_path / "catalog.json"),
        gateway_status_file=str(tmp_path / "status.json"),
    )
    assert gateway.gateway_view(settings, frozenset(), administrator=True).status.state == "current"
    assert (
        gateway.gateway_view(settings, frozenset(), administrator=True).status.reason == "mismatch"
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"schema_version": 1},
        {"schema_version": True},
        {"endpoints": []},
        {"diagnostic": "private-body"},
    ],
)
def test_invalid_catalog_fails_closed(projection, tmp_path, invalid):
    (tmp_path / "catalog.json").write_text(json.dumps({**catalog(), **invalid}))
    with pytest.raises(GatewayUnavailableError):
        gateway.gateway_view(projection, frozenset(), administrator=True)


def test_grouped_wire_and_separate_status_versions():
    parsed = GatewayCatalog.model_validate(catalog())
    wire = parsed.model_dump(by_alias=True)
    assert set(wire) == {
        "schema_version",
        "catalog_revision",
        "policy_revision",
        "profiles",
        "self-hosted-api-providers",
        "external-api-providers",
        "external-subscription-providers",
        "mcp-servers",
    }
    assert GatewayStatus.model_validate_json(json.dumps(status())).schema_version == 1
    for version in (1, True, 2.0, "2"):
        with pytest.raises(ValueError):
            GatewayCatalog.model_validate({**wire, "schema_version": version})


@pytest.mark.parametrize(
    "mutation", ["entry", "destination", "owner", "endpoint", "profile", "refs", "modes", "auth"]
)
def test_grouped_ambiguity_fails_closed(mutation):
    data = catalog()
    first, second = data["external-subscription-providers"]
    destination = first["destinations"][0]
    if mutation == "entry":
        second["id"] = first["id"]
    elif mutation == "destination":
        second["destinations"][0]["id"] = destination["id"]
    elif mutation == "owner":
        first["provider_id"] = "other"
    elif mutation == "endpoint":
        destination["endpoint_ids"] = ["hidden"]
    elif mutation == "profile":
        destination["profile_ids"] = ["unknown"]
    elif mutation == "refs":
        destination["endpoint_ids"] *= 2
    elif mutation == "modes":
        destination["credential_modes"] *= 2
    else:
        first["routes"][0]["caller_auth_modes"] *= 2
    with pytest.raises(ValueError):
        GatewayCatalog.model_validate(data)


def test_shared_proxy_is_observed_once_and_must_be_identical(projection, tmp_path):
    data = catalog()
    first, second = data["external-subscription-providers"]
    second["routes"] = deepcopy(first["routes"])
    second["destinations"][0]["endpoint_ids"] = ["visible"]
    (tmp_path / "catalog.json").write_text(json.dumps(data))
    view = gateway.gateway_view(projection, frozenset(), administrator=True)
    assert len(view.status.endpoints) == 1
    second["routes"][0]["url"] = "https://different.example.test"
    with pytest.raises(ValueError):
        GatewayCatalog.model_validate(data)
    second["routes"] = deepcopy(first["routes"])
    first["routes"][0]["entry_mode"] = second["routes"][0]["entry_mode"] = "api"
    with pytest.raises(ValueError):
        GatewayCatalog.model_validate(data)


def test_physical_endpoint_and_provider_limits_are_aggregate():
    data = catalog()
    prototype = data["external-subscription-providers"][0]
    entries = []
    for index in range(256):
        entry = deepcopy(prototype)
        identity = f"entry-{index}"
        entry["id"] = identity
        entry["provider_id"] = "shared-provider-namespace"
        entry["routes"][0]["id"] = identity
        destination = entry["destinations"][0]
        destination.update(id=identity, provider_id=entry["provider_id"], endpoint_ids=[identity])
        entries.append(entry)
    data["external-subscription-providers"] = entries[:128]
    data["external-api-providers"] = entries[128:]
    assert len(GatewayCatalog.model_validate(data).endpoints) == 256
    extra = deepcopy(entries[-1])
    extra["id"] = "extra"
    extra["routes"][0]["id"] = "extra"
    extra["destinations"][0].update(id="extra", endpoint_ids=["extra"])
    data["mcp-servers"] = [extra]
    with pytest.raises(ValueError):
        GatewayCatalog.model_validate(data)
    data["mcp-servers"] = []
    extra["routes"] = []
    extra["destinations"] = []
    data["self-hosted-api-providers"] = [extra]
    with pytest.raises(ValueError):
        GatewayCatalog.model_validate(data)


@pytest.mark.parametrize(
    "modes,grants,expected",
    [
        (["caller_supplied"], [], ["caller_supplied"]),
        (["company"], [], []),
        (["company"], ["provider:example:company-use"], ["company"]),
        ([], ["provider:example:company-use"], []),
    ],
)
def test_credential_modes_require_provision_and_company_permission(modes, grants, expected):
    data = catalog()
    entry = data["external-subscription-providers"][0]
    entry["provider_id"] = "example"
    destination = entry["destinations"][0]
    destination["provider_id"] = "example"
    destination["credential_modes"] = [
        {"source": source, "required_permissions": []} for source in modes
    ]
    permissions = frozenset(destination["required_permissions"] + grants)
    filtered = gateway._entitled(GatewayCatalog.model_validate(data), permissions)
    assert [mode.source for mode in filtered.destinations[0].credential_modes] == expected
