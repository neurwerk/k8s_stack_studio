"""FastAPI application entry point for the AI Stack Studio backend.

Runs two separate ASGI apps on different ports:
  - App port (4010):     authenticated API → exposed via HTTPRoute
  - Mgmt port (4090):    /health + /metrics → internal-only (pod probes + Prometheus)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as get_version

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.status import (
    HTTP_502_BAD_GATEWAY,
    HTTP_504_GATEWAY_TIMEOUT,
)

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.admin import router as admin_router
from k8s_stack_studio.controllers.api_keys import router as api_keys_router
from k8s_stack_studio.controllers.logs import router as logs_router
from k8s_stack_studio.controllers.policy_engine import router as policy_engine_router
from k8s_stack_studio.controllers.session import router as session_router
from k8s_stack_studio.controllers.usage import router as usage_router
from k8s_stack_studio.lib.auth import configure_auth
from k8s_stack_studio.lib.exceptions import (
    PiiEngineRequestError,
    PiiEngineTimeoutError,
    PiiEngineUnavailableError,
)
from k8s_stack_studio.lib.http_client import http_client_lifespan

_logger = logging.getLogger(__name__)


def _create_app_common() -> tuple[Settings, Instrumentator]:
    """Shared setup: settings, logging, and metrics instrumentator."""
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/health", "/metrics"],
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    )

    return settings, instrumentator


def create_app() -> FastAPI:
    """Build the authenticated FastAPI application (port 4010)."""
    settings, _ = _create_app_common()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _logger.info("Studio API starting (authenticated)")
        async with http_client_lifespan(_app):
            yield
        _logger.info("Studio API shutting down")

    app = FastAPI(
        title="AI Stack Studio",
        version=get_version("k8s-stack-studio"),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )

    # CORS — allow the Next.js dev server origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Keycloak auth middleware (deny-by-default) ---
    configure_auth(app, settings)

    # --- Routers ---
    app.include_router(policy_engine_router)
    app.include_router(admin_router)
    app.include_router(api_keys_router)
    app.include_router(logs_router)
    app.include_router(usage_router)
    app.include_router(session_router)

    # --- Version endpoint (unauthenticated, public) ---
    @app.get("/api/version")
    async def version() -> dict[str, str]:
        return {"version": get_version("k8s-stack-studio")}

    # --- Exception handlers: map PII Engine domain exceptions to HTTP ---
    @app.exception_handler(PiiEngineUnavailableError)
    async def _unavailable(_req: Request, exc: PiiEngineUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_502_BAD_GATEWAY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(PiiEngineTimeoutError)
    async def _timeout(_req: Request, exc: PiiEngineTimeoutError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_504_GATEWAY_TIMEOUT,
            content={"detail": str(exc)},
        )

    @app.exception_handler(PiiEngineRequestError)
    async def _analyze_error(_req: Request, exc: PiiEngineRequestError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail)},
        )

    return app


def create_mgmt_app() -> FastAPI:
    """Build the unauthenticated management app (port 4090).

    Only exposes /health and /metrics — no auth, no CORS, no API routes.
    This app is never exposed through the HTTPRoute (internal pod probes only).
    """
    _settings, instrumentator = _create_app_common()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _logger.info("Studio mgmt API starting")
        yield
        _logger.info("Studio mgmt API shutting down")

    app = FastAPI(lifespan=_lifespan, docs_url=None, redoc_url=None)

    # Health check
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Prometheus metrics
    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


def main() -> None:
    """CLI entry point — start the main authenticated server.

    Use K8S_STUDIO_HOST / K8S_STUDIO_PORT to override defaults.
    """
    settings = Settings()
    uvicorn.run(
        "k8s_stack_studio.main:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
        log_level=settings.log_level,
    )


def mgmt() -> None:
    """CLI entry point — start the internal management server.

    Use K8S_STUDIO_HOST / K8S_STUDIO_MGMT_PORT to override defaults.
    """
    settings = Settings()
    uvicorn.run(
        "k8s_stack_studio.main:create_mgmt_app",
        host=settings.host,
        port=settings.mgmt_port,
        factory=True,
        log_level=settings.log_level,
    )
