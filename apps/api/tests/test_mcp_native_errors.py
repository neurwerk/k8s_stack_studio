"""Native admission errors stay useful without exposing upstream content or identity."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers import mcp
from k8s_stack_studio.lib.auth import StudioAdmissionMiddleware, StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.models.mcp import McpRegistration


@pytest.mark.parametrize(
    ("native_status", "code", "stage"),
    [
        (401, "mcp-native-rejected", "native-request"),
        (403, "mcp-native-rejected", "native-request"),
        (503, "mcp-native-unavailable", "native-request"),
        (None, "mcp-native-unavailable", "native-request"),
        (200, "mcp-native-configuration-error", "native-configuration"),
        (400, "mcp-native-check-failed", "native-admission"),
        (429, None, None),
    ],
)
async def test_tool_admission_errors_are_safe_and_do_not_reach_gateway(
    native_status, code, stage, monkeypatch, caplog
):
    settings = Settings(
        mcp_catalog_enabled=True,
        mcp_gateway_url="https://gateway.example.test",
        mcp_catalog=[
            McpRegistration(
                id="sample",
                name="Sample",
                authentication_model="no-authentication",
                gateway_id="gateway",
                server_id="server",
            )
        ],
        contextforge_account_onboarding_enabled=True,
        contextforge_url="https://native.example.test",
        contextforge_service_token=SecretStr("service-secret"),
        contextforge_team_id="fixed-team",
        contextforge_global_role_id="global-empty",
        contextforge_team_role_id="team-invoke",
    )
    principal = StudioPrincipal(
        "caller-subject",
        frozenset({"studio-user"}),
        frozenset({"llm:invoke", "mcp:sample:invoke"}),
        {"email": "caller@example.test", "email_verified": True},
    )

    def unexpected_gateway(*args, **kwargs):
        pytest.fail("Failed native admission must not reach the gateway")

    monkeypatch.setattr(mcp, "gateway_client", unexpected_gateway)
    requests = []

    def upstream(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/teams/fixed-team"
        if native_status is None:
            raise httpx.ConnectError("private-exception-text", request=request)
        return httpx.Response(
            native_status,
            json={"detail": "private-upstream-body", "id": "wrong-team"},
            headers={"retry-after": "99999", "x-private": "private-response-header"},
        )

    app = FastAPI()
    app.include_router(mcp.router)
    app.add_middleware(StudioAdmissionMiddleware)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.middleware("http")
    async def identity(request, call_next):
        request.scope["user"] = principal
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as native:
        app.state.contextforge_admin_client = native
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://studio.example.test"
        ) as client:
            response = await client.post(
                "/api/me/mcp/sample/tools",
                json={},
                headers={"authorization": "Bearer caller-secret"},
            )

    assert len(requests) == 1
    assert response.status_code == (429 if native_status == 429 else 502)
    assert response.headers["cache-control"] == "no-store"
    assert isinstance(response.json()["detail"], str)
    assert response.headers.get("x-mcp-error-code") == code
    records = [record for record in caplog.records if record.name == mcp.__name__]
    if native_status == 429:
        assert response.headers["retry-after"] == "3600"
        assert not records
    else:
        assert "retry-after" not in response.headers
        # Local configuration validation carries no upstream rejection status.
        logged_status = None if native_status == 200 else native_status
        assert [record.getMessage() for record in records] == [
            f"MCP native failure: category={code} stage={stage} status={logged_status}"
        ]
        assert records[0].exc_info is None
    if native_status in {401, 403}:
        assert "rejected" in response.json()["detail"]
        assert "account status in Studio" in response.json()["detail"]
    for private in (
        "caller@example.test",
        "caller-subject",
        "caller-secret",
        "service-secret",
        "private-exception-text",
        "private-upstream-body",
        "private-response-header",
    ):
        assert private not in response.text + str(response.headers) + caplog.text
