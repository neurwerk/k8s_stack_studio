"""Public popup-only forwarding; native ContextForge still owns all OAuth state/tokens."""

from __future__ import annotations

import asyncio
import json
import re
import secrets

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.http_client import _create_client

router = APIRouter(tags=["mcp"])

# Exact v1.0.11 success-page envelope. Never relay its HTML, gateway names or headers.
_NATIVE_POPUP = re.compile(
    r"<!DOCTYPE html><html><head><title>OAuth Authorization Successful</title></head>"
    r'<body><script nonce="[A-Za-z0-9_+/=-]{0,128}">'
    r"\(function\(\)\{if\(window\.opener&&!window\.opener\.closed\)\{"
    r"window\.opener\.postMessage\((\{[^\n]+\}),'\*'\);window\.close\(\);\}\}\)\(\)</script>"
    r"<p>Authorization successful\. This window will close automatically\.</p></body></html>"
)


def _popup_response(settings: Settings, status_code: int) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    status = "success" if status_code == 200 else "error"
    target = json.dumps(settings.contextforge_oauth_studio_origin).replace("<", "\\u003c")
    return HTMLResponse(
        f"<!DOCTYPE html><html><head><title>Provider connection</title></head><body>"
        f'<script nonce="{nonce}">if(window.opener&&!window.opener.closed){{'
        f'window.opener.postMessage({{"type":"oauth_callback","status":"{status}"}},{target});'
        f"window.close();}}</script><p>Close this window and check your connection in Studio.</p>"
        f"</body></html>",
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
            ),
        },
    )


async def _native_popup_succeeded(settings: Settings, code: str, state: str) -> bool:
    # A fresh, short-lived client cannot share a user's or provisioner's cookie jar.
    request = httpx.Request(
        "GET",
        settings.contextforge_url.rstrip("/") + "/oauth/callback",
        params={"code": code, "state": state},
    )
    async with _create_client(
        verify=settings.contextforge_ca_cert or True, trust_env=False
    ) as client:
        response = await client.send(request, auth=None, follow_redirects=False, stream=True)
        try:
            if (
                response.status_code != 200
                or response.headers.get("content-type", "").split(";", 1)[0] != "text/html"
                or "set-cookie" in response.headers
            ):
                return False
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > 16_384:
                    return False
                body.extend(chunk)
        finally:
            await response.aclose()
    match = _NATIVE_POPUP.fullmatch(body.decode("utf-8"))
    if not match:
        return False
    payload = json.loads(match[1])
    return (
        isinstance(payload, dict)
        and set(payload) == {"type", "status", "gatewayId", "gatewayName"}
        and payload["type"] == "oauth_callback"
        and payload["status"] == "success"
        and isinstance(payload["gatewayId"], str)
        and isinstance(payload["gatewayName"], str)
    )


@router.get("/oauth/callback", include_in_schema=False)
async def oauth_callback(
    request: Request, settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    """Reject non-popup input before native exchange; expose only a constant status hint."""
    if not settings.mcp_connections_enabled:
        return _popup_response(settings, 404)
    if len(request.scope.get("query_string", b"")) > 8192:
        return _popup_response(settings, 400)
    params = request.query_params
    if (
        len(params) != len(params.multi_items())
        or not set(params) <= {"code", "state", "error", "error_description"}
        or not re.fullmatch(r"popup\.[A-Za-z0-9_-]{20,512}", params.get("state", ""))
        or len(params.get("error", "")) > 100
        or len(params.get("error_description", "")) > 500
    ):
        return _popup_response(settings, 400)
    # Provider denial needs no exchange. Never forward/log/render provider error text.
    code = params.get("code", "")
    if params.get("error") or not 1 <= len(code) <= 2048 or not all(" " <= c <= "~" for c in code):
        return _popup_response(settings, 400)
    try:
        async with asyncio.timeout(30):
            succeeded = await _native_popup_succeeded(settings, code, params["state"])
    except (httpx.HTTPError, ValueError, RecursionError, TimeoutError):
        succeeded = False
    return _popup_response(settings, 200 if succeeded else 502)
