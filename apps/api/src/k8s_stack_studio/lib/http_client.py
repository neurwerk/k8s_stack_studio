"""Shared httpx.AsyncClient factory and lifespan management.

Provides a single-argument ``request`` factory so every dependency can get a client
without re-creating one.  The client is attached to ``app.state`` at startup and
closed at shutdown.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.exceptions import PiiEngineTlsConfigError


def _create_client(verify: str | bool = True, *, trust_env: bool = True) -> httpx.AsyncClient:
    """Build the shared client, optionally verifying TLS against a CA bundle.

    Args:
        verify: Path to a CA cert bundle, the system trust store by default, or
            ``False`` for a caller-validated loopback-only development client.
        trust_env: Whether to honor ambient HTTP proxy and CA environment variables.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(15.0),
        verify=verify,
        trust_env=trust_env,
    )


def _create_pii_engine_client(settings: Settings) -> httpx.AsyncClient:
    """Build the isolated, workload-authenticated PII Engine client."""
    if not all((settings.pii_engine_client_cert, settings.pii_engine_client_key)):
        raise PiiEngineTlsConfigError
    if not settings.pii_engine_allow_insecure_local and not settings.pii_engine_ca_cert:
        raise PiiEngineTlsConfigError

    if settings.pii_engine_allow_insecure_local:
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.CERT_NONE
    else:
        tls_context = ssl.create_default_context(cafile=settings.pii_engine_ca_cert)
    tls_context.load_cert_chain(
        certfile=settings.pii_engine_client_cert,
        keyfile=settings.pii_engine_client_key,
    )
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.pii_engine_timeout),
        verify=tls_context,
        trust_env=False,
    )


@asynccontextmanager
async def http_client_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Attach a shared httpx.AsyncClient to ``app.state.http_client``."""
    settings = Settings()
    client = _create_client()
    opensearch_client = _create_client(verify=settings.opensearch_tls_verify, trust_env=False)
    pii_engine_client = _create_pii_engine_client(settings)
    app.state.http_client = client
    app.state.opensearch_client = opensearch_client
    app.state.pii_engine_client = pii_engine_client
    try:
        yield
    finally:
        await client.aclose()
        await opensearch_client.aclose()
        await pii_engine_client.aclose()


async def get_http_client(request: Request) -> httpx.AsyncClient:
    """FastAPI dependency: return the shared httpx.AsyncClient."""
    return request.app.state.http_client
