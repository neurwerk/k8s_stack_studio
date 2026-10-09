"""Production MCP setup handlers and worker, with real isolated PostgreSQL schemas."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest

from k8s_stack_studio import main, mcp_store, mcp_worker, notice_store
from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.contextforge import (
    DISCOVERY_ROLE_MARKER,
    INVOCATION_PERMISSIONS,
    PROVISIONING_PERMISSIONS,
    PUBLISHING_PERMISSIONS,
)
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.mcp_credentials import CredentialRecord, McpSetupError
from k8s_stack_studio.lib.mcp_publication import personal_snapshot, publication_snapshot
from k8s_stack_studio.models.mcp import McpRegistration
from tests.test_mcp_admin_discovery import admin_projection, native_grant


@pytest.fixture
async def database():
    dsn = os.environ.get("MCP_SETUP_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set MCP_SETUP_TEST_DATABASE_URL to an isolated local PostgreSQL database")
    schema = "mcp_test_" + uuid4().hex
    conn = await asyncpg.connect(dsn)
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    isolated = dsn + ("&" if "?" in dsn else "?") + "search_path=" + schema
    try:
        await notice_store.migrate(isolated)
        yield isolated
    finally:
        await conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await conn.close()


def principal(subject="one", *, roles=None, grants=None, verified=True):
    return StudioPrincipal(
        subject,
        frozenset(roles if roles is not None else {"studio-user", "mcp-admin"}),
        frozenset(
            grants
            if grants is not None
            else {
                "llm:invoke",
                "mcp:github:invoke",
                "mcp:brave:invoke",
                "mcp:context7:invoke",
            }
        ),
        {"email": subject + "@example.test", "email_verified": verified},
    )


def setup_projection(tmp_path, dsn):
    settings, data = admin_projection(tmp_path)
    items = [
        McpRegistration.model_validate(
            {
                "id": identity,
                "name": identity.title(),
                "authentication_model": authentication,
                "gateway_id": "gateway-" + identity,
                "server_id": "server-" + identity,
                "upstream_url": "https://provider.example.test/mcp",
                "credential": {
                    "owner": owner,
                    "required": required,
                    "method": method,
                    "header": header,
                },
                "oauth_authorization_origin": "https://provider.example.test"
                if identity == "github"
                else "",
            }
        )
        for identity, authentication, owner, required, method, header in [
            (
                "context7",
                "no-authentication",
                "shared",
                False,
                "gateway-header",
                "CONTEXT7_API_KEY",
            ),
            ("brave", "shared-authentication", "shared", True, "upstream-env", ""),
            ("github", "individual-authentication", "individual", True, "oauth", ""),
        ]
    ]
    (data / "studio.json").write_text(json.dumps([item.model_dump() for item in items]))
    (data / "setup_mode").write_text("studio-v1")
    (data / "publication.json").write_text(
        json.dumps(
            {
                "catalog_hash": "a" * 64,
                "checked_at": datetime.now(UTC).isoformat(),
                "integrations": [
                    {"id": item.id, "state": "pending-discovery", "error_code": None}
                    for item in items
                ],
            }
        )
    )
    return Settings.model_validate(
        {
            **settings.model_dump(),
            "mcp_setup_enabled": True,
            "notice_database_url": dsn,
            "mcp_catalog": items,
        }
    )


class Native:
    def __init__(self, settings):
        """Simulate only the native endpoints used by production setup."""
        self.settings = settings
        self.items = {item.id: item for item in settings.mcp_catalog}
        self.tools = {identity: ["read"] for identity in self.items}
        self.members = {identity: [] for identity in self.items}
        self.grants = {}
        self.revoked = set()
        self.calls = []
        self.refresh_status = 200
        self.refresh_names = ["read", "new"]
        self.unavailable = False
        self.unconfirmed = False
        self.owner_conflict = False

    def __call__(self, request):
        self.calls.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        if self.unavailable:
            return httpx.Response(502, text="private-upstream-error")
        path, method = request.url.path, request.method
        if path.startswith(("/rbac/", "/auth/", "/teams/")):
            assert request.headers["x-contextforge-account-email"] == "provisioner@example.test"
            return httpx.Response(200, json=self.account(request))
        if path.endswith("/tools/refresh"):
            identity = path.split("/")[2].removeprefix("gateway-")
            assert method == "POST"
            assert dict(request.url.params) == {
                "include_resources": "false",
                "include_prompts": "false",
            }
            email = request.headers["x-contextforge-account-email"]
            assert email in self.grants
            self.tools[identity] = self.refresh_names.copy()
            self.members[identity] = [
                value
                for value in self.members[identity]
                if value.removeprefix(identity + "-") in self.refresh_names
            ]
            return httpx.Response(
                self.refresh_status,
                json={
                    "gateway_id": "gateway-" + identity,
                    "success": True,
                    "error": None,
                    "validation_errors": [],
                },
            )
        if path.startswith("/servers/"):
            identity = path.split("/")[-1].removeprefix("server-")
            if method == "PUT":
                assert request.headers["x-contextforge-account-email"] == "provisioner@example.test"
                body = json.loads(request.content)
                assert set(body) == {"associated_tools"}
                self.members[identity] = body["associated_tools"] + (
                    ["foreign"] if self.unconfirmed else []
                )
            return httpx.Response(
                200,
                json={
                    "id": "server-" + identity,
                    "teamId": "fixed-team",
                    "visibility": "public",
                    "enabled": True,
                    "oauthEnabled": False,
                    "ownerEmail": "foreign@example.test"
                    if self.owner_conflict
                    else "provisioner@example.test",
                    "description": "neurwerk-contextforge/studio-v1/gateway-" + identity,
                    "associatedToolIds": self.members[identity],
                    "associatedResources": [],
                    "associatedPrompts": [],
                    "associatedA2aAgents": [],
                },
            )
        if path.startswith("/gateways/"):
            identity = path.split("/")[-1].removeprefix("gateway-")
            item = self.items[identity]
            return httpx.Response(
                200,
                json={
                    "id": item.gateway_id,
                    "url": item.upstream_url,
                    "teamId": "fixed-team",
                    "visibility": "public",
                    "enabled": True,
                    "authType": "oauth" if identity == "github" else None,
                    "oauthConfig": {
                        "authorization_url": "https://provider.example.test/authorize",
                        "grant_type": "authorization_code",
                        "redirect_uri": self.settings.contextforge_oauth_callback_url,
                    },
                },
            )
        assert path == "/tools" and method == "GET"
        identity = request.url.params["gateway_id"].removeprefix("gateway-")
        return httpx.Response(
            200,
            json=[
                {
                    "originalName": name,
                    "name": "native_" + name,
                    "id": identity + "-" + name,
                    "gatewayId": "gateway-" + identity,
                    "teamId": "fixed-team",
                    "integrationType": "MCP",
                    "enabled": True,
                    "description": "Tool " + name,
                }
                for name in self.tools[identity]
            ],
        )

    def account(self, request):
        path = request.url.path
        email = path.split("/")[-1] if path.startswith("/auth/") else path.split("/")[-2]
        if path.startswith("/auth/"):
            return {
                "email": email,
                "is_active": email not in self.revoked,
                "is_admin": False,
                "email_verified": True,
            }
        if path == "/teams/fixed-team":
            return {"id": "fixed-team", "is_active": True, "is_personal": False}
        if path == "/teams/fixed-team/members":
            return {
                "members": [
                    {
                        "user_email": email,
                        "team_id": "fixed-team",
                        "is_active": True,
                        "role": "owner" if email == "provisioner@example.test" else "member",
                    }
                    for email in [
                        "provisioner@example.test",
                        "one@example.test",
                        "two@example.test",
                    ]
                ]
            }
        if path.startswith("/rbac/roles/"):
            role = path.split("/")[-1]
            permissions = {
                "service": PROVISIONING_PERMISSIONS | PUBLISHING_PERMISSIONS,
                "global-empty": set(),
                "team-invoke": INVOCATION_PERMISSIONS,
                "admin-discovery": {"gateways.update"},
            }[role]
            return {
                "id": role,
                "name": "contextforge-tool-discovery",
                "description": DISCOVERY_ROLE_MARKER,
                "is_active": True,
                "inherits_from": None,
                "is_system_role": False,
                "scope": "global" if role in {"service", "global-empty"} else "team",
                "permissions": sorted(permissions),
            }
        assert path.startswith("/rbac/users/")
        if request.method == "POST":
            self.grants[email] = native_grant(email) | json.loads(request.content)
            return self.grants[email]
        roles = (
            ["service"] if email == "provisioner@example.test" else ["global-empty", "team-invoke"]
        )
        return [
            {
                "role_id": role,
                "user_email": email,
                "is_active": True,
                "expires_at": None,
                "scope": "global" if role != "team-invoke" else "team",
                "scope_id": None if role != "team-invoke" else "fixed-team",
            }
            for role in roles
        ] + ([self.grants[email]] if email in self.grants else [])


@pytest.fixture
async def setup(tmp_path, database, monkeypatch):
    settings = setup_projection(tmp_path, database)
    native = Native(settings)
    monkeypatch.setattr(
        main, "configure_auth", lambda app, _: app.add_middleware(StudioAdmissionMiddleware)
    )
    app = main.create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.principal = principal()

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = app.state.principal
        return await call_next(request)

    record = CredentialRecord("", "initial", "", 1)
    credentials = SimpleNamespace(read=AsyncMock(return_value=record), write=AsyncMock())
    activation = SimpleNamespace(wait=AsyncMock())
    app.state.mcp_credentials = credentials
    app.state.mcp_activation = activation
    async with httpx.AsyncClient(transport=httpx.MockTransport(native)) as transport:
        app.state.contextforge_admin_client = transport
        app.state.contextforge_oauth_client = transport
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="https://studio.example.test",
            headers={
                "origin": settings.contextforge_oauth_studio_origin,
                "authorization": "Bearer caller-secret",
                "x-contextforge-account-email": "forged@example.test",
            },
        ) as client:
            yield SimpleNamespace(
                app=app,
                client=client,
                settings=settings,
                native=native,
                credentials=credentials,
                activation=activation,
            )


async def change(setup, kind, *, identity="github", revision=None, **body):
    states = await mcp_store.setups(setup.settings.notice_dsn)
    response = await setup.client.post(
        f"/api/admin/mcp/{identity}/{kind}",
        json={
            "revision": states.get(identity, {}).get("revision", 0)
            if revision is None
            else revision,
            "operation_id": str(uuid4()),
            **body,
        },
    )
    assert response.status_code == (200 if kind == "refresh" else 202), response.text
    return response.json()


async def process(setup, operation):
    await mcp_worker._process(setup.app, setup.settings, UUID(operation["id"]))
    return (await mcp_store.setups(setup.settings.notice_dsn))["github"]


async def test_admin_and_refresh_admission_and_secret_redaction(setup, caplog):
    for roles in ({"studio-user"}, {"mcp-admin"}, set()):
        setup.app.state.principal = principal(roles=roles)
        for method, suffix in [
            ("GET", ""),
            ("GET", "/github/tools"),
            ("POST", "/github/publish"),
            ("POST", "/github/disable"),
            ("POST", "/github/refresh"),
        ]:
            response = await setup.client.request(method, "/api/admin/mcp" + suffix, json={})
            assert response.status_code == 403
    setup.app.state.principal = principal()
    for who in (principal(grants=set()), principal(verified=False)):
        setup.app.state.principal = who
        response = await setup.client.post(
            "/api/admin/mcp/github/refresh",
            json={
                "revision": 0,
                "operation_id": str(uuid4()),
            },
        )
        assert response.status_code == 403
    setup.app.state.principal = principal()
    for extra in (
        {"revision": "entered-secret"},
        {"api_key": {"raw": "entered-secret"}},
        {"unknown": "entered-secret"},
        {"api_key": "entered-secret\ninvalid"},
    ):
        response = await setup.client.post(
            "/api/admin/mcp/context7/publish",
            json={
                "revision": 0,
                "operation_id": str(uuid4()),
                "selected_tools": [],
                **extra,
            },
        )
        assert response.status_code == 422 and "entered-secret" not in response.text
    assert not setup.native.calls
    setup.credentials.write.assert_not_awaited()
    assert not await mcp_store.setups(setup.settings.notice_dsn)
    assert "entered-secret" not in caplog.text and "caller-secret" not in caplog.text


async def test_exact_publish_disable_and_saved_selection_survive_restart(setup):
    # GET reads definitions only, without selecting or contacting a provider.
    assert (await setup.client.get("/api/admin/mcp/github/tools")).json()[0]["name"] == "read"
    assert all(request.method == "GET" for request in setup.native.calls)
    operation = await change(setup, "publish", selected_tools=["read"])
    state = await process(setup, operation)
    assert state["operation"].state == "succeeded"
    assert setup.native.members["github"] == ["github-read"]
    live, status = await personal_snapshot(setup.settings)
    assert status["github"].state == "published"
    assert live.mcp_catalog[2].tool_names == {"read": "github_native_read"}
    disable = await change(setup, "disable")
    # A queued change is progress, not evidence that published membership disappeared.
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "published"
    state = await process(setup, disable)
    assert state["selected_tools"] == ["read"] and not state["enabled"]
    assert setup.native.members["github"] == []
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "pending-discovery"
    # Reopening settings and reapplying the schema cannot replace Studio choices.
    await notice_store.migrate(setup.settings.notice_dsn)
    assert (await mcp_store.setups(setup.settings.notice_dsn))["github"]["selected_tools"] == [
        "read"
    ]
    state = await process(setup, await change(setup, "publish", selected_tools=["read"]))
    assert state["enabled"]


async def test_concurrent_stale_and_duplicate_intent_are_fenced(setup):
    path = "/api/admin/mcp/github/publish"
    body = {"revision": 0, "operation_id": str(uuid4()), "selected_tools": ["read"]}
    responses = await asyncio.gather(
        setup.client.post(path, json=body), setup.client.post(path, json=body)
    )
    assert [response.status_code for response in responses] == [202, 202]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    for update in ({"operation_id": str(uuid4())}, {"selected_tools": []}):
        assert (await setup.client.post(path, json=body | update)).status_code == 409
    setup.app.state.principal = principal("two")
    assert (await setup.client.post(path, json=body)).status_code == 409
    setup.app.state.principal = principal()
    await process(setup, responses[0].json())
    assert (
        await setup.client.post(path, json=body | {"operation_id": str(uuid4())})
    ).status_code == 409
    # After the first result completes, its idempotency key still returns that result.
    assert (await setup.client.post(path, json=body)).json()["state"] == "succeeded"
    responses = await asyncio.gather(
        *(
            setup.client.post(
                path,
                json={
                    **body,
                    "revision": 1,
                    "operation_id": str(uuid4()),
                },
            )
            for _ in range(2)
        )
    )
    assert sorted(response.status_code for response in responses) == [202, 409]


async def test_worker_crash_retries_exact_membership_without_duplicate_writes(setup, monkeypatch):
    operation = await change(setup, "publish", selected_tools=["read"])
    finish = mcp_store.finish
    monkeypatch.setattr(mcp_store, "finish", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await process(setup, operation)
    assert setup.native.members["github"] == ["github-read"]
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "unavailable"
    monkeypatch.setattr(mcp_store, "finish", finish)
    # Multiple workers race after restart; the session lock permits only one.
    await asyncio.gather(process(setup, operation), process(setup, operation))
    state = (await mcp_store.setups(setup.settings.notice_dsn))["github"]
    assert state["operation"].state == "succeeded" and not state["publication_uncertain"]
    assert setup.native.members["github"] == ["github-read"]


async def test_refresh_uses_each_admin_and_never_selects_new_tools(setup):
    await process(setup, await change(setup, "publish", selected_tools=["read"]))
    for who in ("one", "two"):
        setup.app.state.principal = principal(who)
        operation = await change(setup, "refresh")
        assert operation["state"] == "succeeded"
        refreshes = [
            request for request in setup.native.calls if request.url.path.endswith("/tools/refresh")
        ]
        assert refreshes[-1].headers["x-contextforge-account-email"] == who + "@example.test"
        state = (await mcp_store.setups(setup.settings.notice_dsn))["github"]
        assert state["selected_tools"] == ["read"] and list(state["published_tools"]) == ["read"]
    setup.native.revoked.add("two@example.test")
    count = len(refreshes)
    assert (await change(setup, "refresh"))["state"] == "failed"
    assert (
        len(
            [
                request
                for request in setup.native.calls
                if request.url.path.endswith("/tools/refresh")
            ]
        )
        == count
    )
    # Failure before native mutation preserves the last confirmed publication.
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "published"


async def test_failed_and_interrupted_refresh_reconcile_surviving_publication(setup):
    await process(setup, await change(setup, "publish", selected_tools=["read"]))
    setup.native.refresh_status = 502
    operation = await change(setup, "refresh")
    assert operation["state"] == "failed"
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "published"
    setup.native.refresh_names = ["new"]  # Failed native refresh can remove an old definition.
    operation = await change(setup, "refresh")
    assert operation["state"] == "failed" and not setup.native.members["github"]
    state = (await mcp_store.setups(setup.settings.notice_dsn))["github"]
    assert not state["selected_tools"] and not state["publication_uncertain"]
    # Crash recovery may confirm membership; it must not rediscover as a past admin.
    settings = publication_snapshot(setup.settings)[0]
    operation, _ = await mcp_store.begin(
        settings.notice_dsn,
        "github",
        state["revision"],
        uuid4(),
        "refresh",
        "one",
        {"binding": mcp_store.binding(settings.mcp_catalog[2])},
        phase="refreshing",
    )
    calls = len(
        [request for request in setup.native.calls if request.url.path.endswith("/tools/refresh")]
    )
    state = await process(setup, operation.model_dump(mode="json"))
    assert state["operation"].error_code == "refresh-interrupted"
    assert (
        len(
            [
                request
                for request in setup.native.calls
                if request.url.path.endswith("/tools/refresh")
            ]
        )
        == calls
    )


async def test_unconfirmed_native_write_is_not_success_and_retry_recovers(setup):
    await process(setup, await change(setup, "publish", selected_tools=["read"]))
    state = await process(setup, await change(setup, "publish", selected_tools=["unknown"]))
    assert state["operation"].error_code == "tools-changed-refresh-required"
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "published"
    setup.native.unconfirmed = True
    state = await process(setup, await change(setup, "publish", selected_tools=["read"]))
    assert state["operation"].error_code == "publication-unconfirmed"
    assert state["publication_uncertain"]
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "unavailable"
    setup.native.unconfirmed = False
    state = await process(setup, await change(setup, "disable"))
    assert not state["publication_uncertain"] and setup.native.members["github"] == []
    assert state["selected_tools"] == ["read"]


async def test_shared_key_only_publish_waits_for_activation_and_never_stores_key(setup, caplog):
    secret = "entered-test-key"

    async def write(identity, operation_id, key):
        assert identity == "brave" and key == secret
        setup.credentials.read.return_value = CredentialRecord(
            key, operation_id.replace("-", ""), operation_id, 2
        )
        # The write succeeded but the response was lost. Recovery reads operationId.
        raise McpSetupError("credential-write-unconfirmed")

    setup.credentials.write.side_effect = write
    operation = await change(
        setup, "publish", identity="brave", selected_tools=[], key_action="replace", api_key=secret
    )
    setup.activation.wait.side_effect = TimeoutError
    await mcp_worker._process(setup.app, setup.settings, UUID(operation["id"]))
    state = (await mcp_store.setups(setup.settings.notice_dsn))["brave"]
    assert state["operation"].error_code == "activation-timeout" and not state["enabled"]
    assert setup.native.members["brave"] == []
    setup.activation.wait.side_effect = None
    retry = await change(
        setup, "publish", identity="brave", selected_tools=[], key_action="replace", api_key="  "
    )
    await mcp_worker._process(setup.app, setup.settings, UUID(retry["id"]))
    setup.credentials.write.assert_awaited_once()
    state = (await mcp_store.setups(setup.settings.notice_dsn))["brave"]
    assert state["key_configured"] and state["operation"].state == "succeeded"
    assert (await change(setup, "refresh", identity="brave"))["state"] == "succeeded"
    publish = await change(setup, "publish", identity="brave", selected_tools=["read"])
    await mcp_worker._process(setup.app, setup.settings, UUID(publish["id"]))
    assert setup.native.members["brave"] == ["brave-read"]
    async with mcp_store.connection(setup.settings.notice_dsn) as conn:
        rows = await conn.fetch(
            "SELECT row_to_json(mcp_operations)::text AS value FROM mcp_operations"
        )
        states = await conn.fetch("SELECT row_to_json(mcp_setups)::text AS value FROM mcp_setups")
    assert secret not in str(rows + states) + caplog.text
    assert secret not in (await setup.client.get("/api/admin/mcp")).text


async def test_required_key_missing_and_lost_key_input_fail_without_publication(setup):
    operation = await change(setup, "publish", identity="brave", selected_tools=[])
    await mcp_worker._process(setup.app, setup.settings, UUID(operation["id"]))
    state = (await mcp_store.setups(setup.settings.notice_dsn))["brave"]
    assert state["operation"].error_code == "api-key-required"
    setup.activation.wait.assert_not_awaited()
    setup.credentials.write.side_effect = McpSetupError("credential-store-unavailable")
    operation = await change(
        setup,
        "publish",
        identity="context7",
        selected_tools=[],
        key_action="replace",
        api_key="lost-test-input",
    )
    await mcp_worker._process(setup.app, setup.settings, UUID(operation["id"]))
    state = (await mcp_store.setups(setup.settings.notice_dsn))["context7"]
    assert state["operation"].error_code == "key-entry-required"


async def test_optional_key_removal_and_credential_change_during_activation(setup):
    async def write(identity, operation_id, key):
        setup.credentials.read.return_value = CredentialRecord(
            key,
            operation_id.replace("-", ""),
            operation_id,
            2,
        )

    setup.credentials.write.side_effect = write
    for key_action, api_key, configured in [
        ("replace", "optional-test-key", True),
        ("remove", "", False),
    ]:
        operation = await change(
            setup,
            "publish",
            identity="context7",
            selected_tools=["read"],
            key_action=key_action,
            api_key=api_key,
        )
        await mcp_worker._process(setup.app, setup.settings, UUID(operation["id"]))
        state = (await mcp_store.setups(setup.settings.notice_dsn))["context7"]
        assert state["operation"].state == "succeeded"
        assert state["key_configured"] is configured
        assert bool(setup.activation.wait.await_args.args[1].api_key) is configured
    assert setup.native.members["context7"] == ["context7-read"]
    for identity, action in [("brave", "remove"), ("github", "replace")]:
        response = await setup.client.post(
            f"/api/admin/mcp/{identity}/publish",
            json={
                "revision": 0,
                "operation_id": str(uuid4()),
                "selected_tools": [],
                "key_action": action,
                "api_key": "test-key" if action == "replace" else "",
            },
        )
        assert response.status_code == 422

    async def race(item, record):
        setup.credentials.read.return_value = CredentialRecord("changed", "c" * 32, "other", 3)

    setup.activation.wait.side_effect = race
    operation = await change(setup, "publish", identity="context7", selected_tools=[])
    await mcp_worker._process(setup.app, setup.settings, UUID(operation["id"]))
    state = (await mcp_store.setups(setup.settings.notice_dsn))["context7"]
    assert state["operation"].error_code == "credential-changed"
    assert setup.native.members["context7"] == ["context7-read"]
    assert (await personal_snapshot(setup.settings))[1]["context7"].state == "published"


async def test_interrupted_refresh_is_honestly_unavailable_until_reconciled(setup, monkeypatch):
    await process(setup, await change(setup, "publish", selected_tools=["read"]))
    from k8s_stack_studio.lib.contextforge_oauth import ContextForgeOAuthClient

    original = ContextForgeOAuthClient.discover
    monkeypatch.setattr(ContextForgeOAuthClient, "discover", AsyncMock(side_effect=TimeoutError))
    # Reading definitions after an ambiguous refresh also fails.
    from k8s_stack_studio.lib.mcp_native_setup import McpNativeSetup

    real_tools = McpNativeSetup.tools
    calls = 0

    async def tools(self, item):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise McpSetupError("native-unavailable")
        return await real_tools(self, item)

    monkeypatch.setattr(McpNativeSetup, "tools", tools)
    operation = await change(setup, "refresh")
    assert operation["state"] == "failed"
    assert setup.native.members["github"] == ["github-read"]
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "unavailable"
    status = (await setup.client.get("/api/admin/mcp")).json()[2]
    assert status["publication_uncertain"] and status["published_tools"] == ["read"]
    monkeypatch.setattr(McpNativeSetup, "tools", real_tools)
    monkeypatch.setattr(ContextForgeOAuthClient, "discover", original)
    assert (await change(setup, "refresh"))["state"] == "succeeded"
    assert (await personal_snapshot(setup.settings))[1]["github"].state == "published"


async def test_catalog_binding_and_native_ownership_conflicts_block_writes(setup):
    operation = await change(setup, "publish", selected_tools=["read"])
    path = (
        Path(setup.settings.contextforge_publication_status_path).parent / "..data" / "studio.json"
    )
    catalog = json.loads(path.read_text())
    catalog[2]["server_id"] = "replacement-server"
    path.write_text(json.dumps(catalog))
    state = await process(setup, operation)
    assert state["operation"].error_code == "catalog-changed"
    assert not setup.native.calls
    catalog[2]["server_id"] = "server-github"
    path.write_text(json.dumps(catalog))
    setup.native.owner_conflict = True
    state = await process(setup, await change(setup, "publish", selected_tools=["read"]))
    assert state["operation"].error_code == "native-ownership-conflict"
    assert not any(request.method == "PUT" for request in setup.native.calls)
