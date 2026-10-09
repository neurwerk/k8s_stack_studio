"""Notice inheritance and key ownership boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from k8s_stack_studio import notice_internal, notice_store
from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.notice_preferences import (
    KeyOverrides,
    UserPreferences,
    _active_key,
    _require_store,
    get_user_preferences,
    put_key_preferences,
    router,
)
from k8s_stack_studio.lib.dependencies import get_current_user_id, get_settings
from k8s_stack_studio.notice_internal import create_app


@pytest.mark.asyncio
async def test_inheritance_is_per_field_and_timing_independent(monkeypatch):
    class Connection:
        async def fetchrow(self, query, *args):
            if "notice_users" in query:
                return dict.fromkeys(notice_store.FIELDS, False)
            return {
                "show_timing": True,
                **{field: None for field in notice_store.FIELDS if field != "show_timing"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(notice_store.asyncpg, "connect", AsyncMock(return_value=Connection()))
    result = await notice_store.read("unused", "self", "key")
    assert result == {field: field == "show_timing" for field in notice_store.FIELDS}


@pytest.mark.asyncio
async def test_key_master_override_and_unscanned_inheritance(monkeypatch):
    class Connection:
        async def fetchrow(self, query, *args):
            if "notice_users" in query:
                return dict.fromkeys(notice_store.FIELDS, False)
            return {
                field: True if field == "notices_enabled" else None for field in notice_store.FIELDS
            }

        async def close(self):
            pass

    monkeypatch.setattr(notice_store.asyncpg, "connect", AsyncMock(return_value=Connection()))
    assert await notice_store.read("unused", "self", "key") == {
        field: field == "notices_enabled" for field in notice_store.FIELDS
    }
    assert await notice_store.read("unused", "self") == dict.fromkeys(notice_store.FIELDS, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("starting_version", [0, 1])
async def test_migration_appends_columns_and_preserves_existing_rows(monkeypatch, starting_version):
    connection = MagicMock()
    connection.transaction.return_value.__aenter__ = AsyncMock()
    connection.transaction.return_value.__aexit__ = AsyncMock()
    connection.fetchval = AsyncMock(return_value=starting_version)
    connection.execute = AsyncMock()
    connection.close = AsyncMock()
    monkeypatch.setattr(notice_store.asyncpg, "connect", AsyncMock(return_value=connection))
    await notice_store.migrate("unused")
    statements = [call.args[0] for call in connection.execute.await_args_list]
    migrations = [statement for statement in statements if "ALTER TABLE notice_users" in statement]
    assert len(migrations) == 1
    migration = migrations[0]
    assert "notices_enabled boolean NOT NULL DEFAULT true" in migration
    assert "show_unscanned_faces boolean NOT NULL DEFAULT true" in migration
    assert "ALTER TABLE notice_keys" in migration
    assert "ADD COLUMN show_unscanned_faces boolean;" in migration
    assert ("CREATE TABLE notice_users" in " ".join(statements)) == (starting_version == 0)
    assert connection.execute.await_args_list[-1].args == (
        "INSERT INTO notice_schema_version (version) VALUES ($1)",
        len(notice_store.MIGRATIONS),
    )


@pytest.mark.asyncio
async def test_nine_fields_written_for_users_and_keys(monkeypatch):
    connection = MagicMock()
    connection.execute = AsyncMock()
    connection.close = AsyncMock()
    monkeypatch.setattr(notice_store.asyncpg, "connect", AsyncMock(return_value=connection))
    user = dict.fromkeys(notice_store.FIELDS, True)
    await notice_store.write("unused", "self", user)
    assert connection.execute.await_args is not None
    query, *args = connection.execute.await_args.args
    assert all(field in query for field in notice_store.FIELDS)
    assert args == ["self", *user.values()]
    key = dict.fromkeys(notice_store.FIELDS, None)
    key["notices_enabled"] = True
    await notice_store.write("unused", "self", key, "key")
    assert connection.execute.await_args is not None
    query, *args = connection.execute.await_args.args
    assert "ON CONFLICT (principal_id, credential_id)" in query
    assert args == ["self", "key", *key.values()]


@pytest.mark.asyncio
async def test_revoked_expired_and_unowned_keys_cannot_be_configured(monkeypatch):
    client = MagicMock()
    response = MagicMock()
    response.json.return_value = [
        {"id": "revoked", "revoked": True, "expires_at": "2099-01-01T00:00:00Z"},
        {"id": "expired", "revoked": False, "expires_at": "2000-01-01T00:00:00Z"},
        {
            "id": "active",
            "revoked": False,
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    ]
    client.get = AsyncMock(return_value=response)
    request = MagicMock()
    request.app = SimpleNamespace(state=SimpleNamespace(http_client=client))
    request.headers.get.return_value = "Bearer verified"
    settings = Settings(keycloak_api_key_bridge_url="http://bridge")
    write = AsyncMock()
    monkeypatch.setattr("k8s_stack_studio.controllers.notice_preferences.write", write)
    overrides = KeyOverrides(**dict.fromkeys(notice_store.FIELDS, None))

    for key_id in ("revoked", "expired", "foreign"):
        with pytest.raises(HTTPException) as error:
            await put_key_preferences(key_id, overrides, request, "self", settings)
        assert error.value.status_code == 404
    write.assert_not_awaited()
    await put_key_preferences("active", overrides, request, "self", settings)
    write.assert_awaited_once()
    client.get.assert_awaited_with(
        "http://bridge/api_keys",
        params={"user_id": "self"},
        headers={"Authorization": "Bearer verified"},
    )


def test_bridge_naive_sqlite_expiry_is_utc():
    future = (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat()
    past = (datetime.now(UTC) - timedelta(days=1)).replace(tzinfo=None).isoformat()
    assert _active_key({"id": "key", "revoked": False, "expires_at": future}, "key")
    assert not _active_key({"id": "key", "revoked": False, "expires_at": past}, "key")


def test_private_listener_disables_query_access_logs(monkeypatch):
    settings = Settings(notice_database_url="postgresql://unused")
    monkeypatch.setattr(notice_internal, "Settings", lambda: settings)
    tls = MagicMock()
    monkeypatch.setattr(notice_internal.ssl, "create_default_context", lambda *args, **kwargs: tls)
    run_app = MagicMock()
    monkeypatch.setattr(notice_internal.web, "run_app", run_app)
    notice_internal.main()
    assert run_app.call_args.kwargs["access_log"] is None


def test_missing_fields_and_extra_inputs_are_rejected():
    with pytest.raises(ValidationError):
        UserPreferences.model_validate({"show_no_pii": True})
    with pytest.raises(ValidationError):
        KeyOverrides.model_validate(
            {**dict.fromkeys(notice_store.FIELDS, None), "principal_id": "other"}
        )
    with pytest.raises(ValidationError):
        UserPreferences.model_validate(
            {**dict.fromkeys(notice_store.FIELDS, True), "notices_enabled": "false"}
        )
    with pytest.raises(ValidationError):
        UserPreferences.model_validate(
            {**dict.fromkeys(notice_store.FIELDS, True), "show_no_faces": None}
        )
    with pytest.raises(ValidationError):
        KeyOverrides.model_validate(
            {**dict.fromkeys(notice_store.FIELDS, None), "show_unscanned_faces": "off"}
        )


@pytest.mark.asyncio
async def test_private_route_rejects_connections_without_client_certificate():
    async with TestClient(TestServer(create_app(Settings()))) as client:
        response = await client.get("/internal/v1/notice-preferences?principal_id=self")
        assert response.status == 403


@pytest.mark.asyncio
async def test_private_route_uses_verified_client_identity_and_lookup(monkeypatch):
    read = AsyncMock(return_value=dict.fromkeys(notice_store.FIELDS, True))
    monkeypatch.setattr("k8s_stack_studio.notice_internal.read", read)
    app = create_app(Settings(notice_database_url="postgresql://unused"))
    route = next(route for route in app.router.routes() if route.method == "GET")
    assert route.resource is not None
    assert route.resource.canonical == "/internal/v1/notice-preferences"
    transport = MagicMock()
    transport.get_extra_info.return_value = {
        "subject": ((("commonName", "monitor-agentgateway-extproc-studio"),),)
    }
    request = make_mocked_request(
        "GET",
        "/internal/v1/notice-preferences?principal_id=self&credential_id=key",
        transport=transport,
    )
    response = await route.handler(request)
    assert response.status == 200
    assert isinstance(response, web.Response)
    assert isinstance(response.body, (bytes, bytearray))
    assert json.loads(response.body) == dict.fromkeys(notice_store.FIELDS, True)
    read.assert_awaited_once_with("postgresql://unused", "self", "key")
    transport.get_extra_info.return_value = {"subject": ((("commonName", "wrong"),),)}
    with pytest.raises(web.HTTPForbidden):
        await route.handler(request)


def test_notice_dsn_escapes_secret_parts():
    settings = Settings(notice_postgres_host="postgres.local", notice_postgres_password="a/b@c")
    assert settings.notice_dsn == "postgresql://studio:a%2Fb%40c@postgres.local:5432/studio"


@pytest.mark.asyncio
async def test_schema_capability_requires_committed_migration(monkeypatch):
    assert not await notice_store.schema_ready("")
    connection = MagicMock()
    connection.fetchval = AsyncMock(side_effect=[None, len(notice_store.MIGRATIONS)])
    connection.close = AsyncMock()
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(notice_store.asyncpg, "connect", connect)
    assert not await notice_store.schema_ready("postgresql://unused")
    assert await notice_store.schema_ready("postgresql://unused")
    assert connect.await_count == 2
    assert connection.close.await_count == 2


@pytest.mark.asyncio
async def test_disabled_or_missing_schema_returns_503_without_leaking_dsn(monkeypatch):
    with pytest.raises(HTTPException) as disabled:
        _require_store(Settings())
    assert disabled.value.status_code == 503
    read = AsyncMock(side_effect=notice_store.asyncpg.UndefinedTableError("secret connection"))
    monkeypatch.setattr("k8s_stack_studio.controllers.notice_preferences.read", read)
    with pytest.raises(HTTPException) as missing:
        await get_user_preferences("self", Settings(notice_database_url="postgresql://secret"))
    assert missing.value.status_code == 503
    assert "secret" not in str(missing.value.detail)


@pytest.mark.asyncio
async def test_all_notice_routes_return_503_when_storage_disabled():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: "self"
    app.dependency_overrides[get_settings] = lambda: Settings()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method, path in (
            ("GET", "/api/me/notice-preferences"),
            ("PUT", "/api/me/notice-preferences"),
            ("GET", "/api/me/notice-preferences/keys/key"),
            ("PUT", "/api/me/notice-preferences/keys/key"),
        ):
            body = dict.fromkeys(notice_store.FIELDS, True) if method == "PUT" else None
            response = await client.request(method, path, json=body)
            assert response.status_code == 503
            assert response.json() == {"detail": "Notice preferences are unavailable"}


@pytest.mark.asyncio
async def test_self_api_round_trips_nine_strict_flags(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: "verified-user"
    app.dependency_overrides[get_settings] = lambda: Settings(
        notice_database_url="postgresql://unused"
    )
    stored = dict.fromkeys(notice_store.FIELDS, True)
    read = AsyncMock(side_effect=lambda *args: stored.copy())
    write = AsyncMock()
    monkeypatch.setattr("k8s_stack_studio.controllers.notice_preferences.read", read)
    monkeypatch.setattr("k8s_stack_studio.controllers.notice_preferences.write", write)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/me/notice-preferences")
        assert response.status_code == 200
        assert response.json() == stored
        read.assert_awaited_once_with("postgresql://unused", "verified-user")

        stored["notices_enabled"] = False
        stored["show_unscanned_faces"] = False
        response = await client.put("/api/me/notice-preferences", json=stored)
        assert response.status_code == 200
        assert response.json() == stored
        write.assert_awaited_once_with("postgresql://unused", "verified-user", stored)

        for invalid in (
            {**stored, "show_no_faces": "false"},
            {**stored, "show_no_faces": None},
            {**stored, "unknown": True},
        ):
            response = await client.put("/api/me/notice-preferences", json=invalid)
            assert response.status_code == 422
        write.assert_awaited_once()
