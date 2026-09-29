"""Dedicated private HTTPS listener; no Next.js proxy or public API registration."""

from __future__ import annotations

import ssl

from aiohttp import web

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.notice_store import NoticeSchemaError, read


def create_app(settings: Settings) -> web.Application:
    """Build the isolated extProc-only lookup app."""
    app = web.Application(client_max_size=1024)

    async def lookup(request: web.Request) -> web.Response:
        peer = request.transport.get_extra_info("peercert") if request.transport else None
        names = (
            [
                value
                for group in peer.get("subject", ())
                for key, value in group
                if key == "commonName"
            ]
            if isinstance(peer, dict)
            else []
        )
        if names != [settings.notice_client_cn]:
            raise web.HTTPForbidden()
        if set(request.query) - {"principal_id", "credential_id"}:
            raise web.HTTPBadRequest()
        principal = request.query.get("principal_id", "")
        credential = request.query.get("credential_id")
        if any(
            not value
            or len(value) > 128
            or not all(char.isascii() and (char.isalnum() or char in "_.:-") for char in value)
            for value in (principal, *([credential] if credential is not None else []))
        ):
            raise web.HTTPBadRequest()
        result = await read(settings.notice_dsn, principal, credential)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    app.router.add_get("/internal/v1/notice-preferences", lookup)
    return app


def main() -> None:
    """Start the mTLS listener with a required, verified client certificate."""
    settings = Settings()
    if not settings.notice_dsn:
        raise NoticeSchemaError
    tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=settings.notice_tls_ca)
    tls.load_cert_chain(settings.notice_tls_cert, settings.notice_tls_key)
    tls.verify_mode = ssl.CERT_REQUIRED
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    web.run_app(
        create_app(settings),
        host=settings.host,
        port=settings.notice_port,
        ssl_context=tls,
        access_log=None,  # The GET query contains private principal and credential IDs.
    )
