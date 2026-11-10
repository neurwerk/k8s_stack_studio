"""Provider session metadata must not block or influence native OAuth exchange."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers import oauth_callback
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.models.mcp import McpRegistration

STATE = "popup." + "a" * 64
CODE = "synthetic-code"
PARAMS = [("code", CODE), ("state", STATE), ("iss", "https://provider.example.test")]
MARKUP = "<script>synthetic-session-metadata</script>"


@pytest.fixture
def callback_app(monkeypatch):
    settings = Settings(
        mcp_catalog_enabled=True,
        mcp_catalog=[
            McpRegistration(
                id="example",
                name="Example",
                authentication_model="individual-authentication",
                gateway_id="fixed-gateway",
                server_id="fixed-server",
                oauth_authorization_origin="https://provider.example.test",
            )
        ],
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
    )
    requests = []

    def native(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<!DOCTYPE html><html><head><title>OAuth Authorization Successful</title></head>"
                '<body><script nonce="synthetic">'
                "(function(){if(window.opener&&!window.opener.closed){"
                'window.opener.postMessage({"type":"oauth_callback","status":"success",'
                '"gatewayId":"fixed-gateway","gatewayName":"Example"},\'*\');window.close();'
                "}})()</script><p>Authorization successful. This window will close automatically."
                "</p></body></html>"
            ),
        )

    monkeypatch.setattr(
        oauth_callback,
        "_create_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(native)),
    )
    app = FastAPI()
    app.include_router(oauth_callback.router)
    app.dependency_overrides[get_settings] = lambda: settings
    return app, requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [None, MARKUP, MARKUP + "x" * (2048 - len(MARKUP))],
    ids=["absent", "opaque-markup", "maximum-length"],
)
async def test_callback_ignores_optional_session_metadata(callback_app, metadata):
    app, requests = callback_app
    params = PARAMS + ([] if metadata is None else [("session_state", metadata)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://studio.example.test"
    ) as client:
        response = await client.get("/oauth/callback", params=params)
    assert response.status_code == 200
    assert '"status":"success"' in response.text
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url.copy_with(query=None)) == "https://native.example.test/oauth/callback"
    assert request.url.params.multi_items() == [("code", CODE), ("state", STATE)]
    assert MARKUP not in response.text
    assert all(MARKUP not in value for value in response.headers.values())
    assert "session_state" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        [*PARAMS, ("session_state", "x" * 2049)],
        [*PARAMS, ("session_state", "one"), ("session_state", "two")],
        [*PARAMS, ("unknown", "value")],
        [("code", CODE), ("state", "malformed"), ("session_state", MARKUP)],
        [("code", CODE), ("session_state", MARKUP)],
        # Each decoded field fits its cap, but encoded query exceeds the total limit.
        [*PARAMS, ("session_state", "\u2603" * 2048)],
        [("state", STATE), ("error", "access_denied"), ("session_state", MARKUP)],
    ],
    ids=["oversized", "duplicate", "unknown", "bad-state", "missing-state", "total-size", "denial"],
)
async def test_callback_rejects_before_native_exchange(callback_app, params):
    app, requests = callback_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://studio.example.test"
    ) as client:
        response = await client.get("/oauth/callback", params=params)
    assert response.status_code == 400
    assert '"status":"error"' in response.text
    assert requests == []
