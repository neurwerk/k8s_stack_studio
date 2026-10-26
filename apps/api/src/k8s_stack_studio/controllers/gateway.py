"""Read-only gateway presentation and exact anonymous public-root downloads."""

from __future__ import annotations

import hashlib
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_current_principal, get_settings, require_role
from k8s_stack_studio.lib.gateway import gateway_view
from k8s_stack_studio.lib.gateway_files import GatewayUnavailableError
from k8s_stack_studio.lib.gateway_trust import TrustPublication, trust_publication
from k8s_stack_studio.models.gateway import GatewayView

router = APIRouter(tags=["gateway"])


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Gateway information unavailable",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/api/gateway",
    dependencies=[Depends(require_role("studio-user"))],
)
def get_gateway(
    response: Response,
    principal: StudioPrincipal = Depends(get_current_principal),
    settings: Settings = Depends(get_settings),
) -> GatewayView:
    """Return only entitled destinations, modes and referenced configuration."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return gateway_view(settings, principal.agentgateway_roles)
    except GatewayUnavailableError:
        raise _unavailable() from None


@router.get(
    "/api/admin/gateway",
    dependencies=[Depends(require_role("studio-user")), Depends(require_role("gateway-admin"))],
)
def get_admin_gateway(
    response: Response, settings: Settings = Depends(get_settings)
) -> GatewayView:
    """Expose complete configuration; this role grants no invocation permissions."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return gateway_view(settings, frozenset(), administrator=True)
    except GatewayUnavailableError:
        raise _unavailable() from None


def _publication(settings: Settings = Depends(get_settings)) -> TrustPublication:
    try:
        return trust_publication(settings)
    except GatewayUnavailableError:
        raise _unavailable() from None


def _asset(
    request: Request,
    content: bytes | None,
    media_type: str,
    *,
    filename: str | None = None,
    immutable: bool = False,
) -> Response:
    if content is None:
        raise HTTPException(
            status_code=404, detail="Trust asset not found", headers={"Cache-Control": "no-store"}
        )
    headers = {
        "Cache-Control": "public, max-age=86400, immutable" if immutable else "no-store",
        "Content-Length": str(len(content)),
        "X-Content-Type-Options": "nosniff",
        "ETag": f'"{hashlib.sha256(content).hexdigest()}"',
    }
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(
        content=b"" if request.method == "HEAD" else content,
        media_type=media_type,
        headers=headers,
    )


@router.get("/api/gateway/trust/manifest.json")
@router.head("/api/gateway/trust/manifest.json", include_in_schema=False)
def get_trust_manifest(
    request: Request, publication: TrustPublication = Depends(_publication)
) -> Response:
    """Describe current and retained assets using independently derived certificate data."""
    return _asset(request, publication.manifest.model_dump_json().encode(), "application/json")


@router.get("/api/gateway/trust/bundle.pem")
@router.head("/api/gateway/trust/bundle.pem", include_in_schema=False)
def get_trust_bundle(
    request: Request, publication: TrustPublication = Depends(_publication)
) -> Response:
    """Download the current root bundle without caching the moving pointer."""
    return _asset(
        request,
        publication.bundles[publication.manifest.current_version],
        "application/x-pem-file",
        filename="inspection-roots.pem",
    )


@router.get("/api/gateway/trust/bundles/{version}.pem")
@router.head("/api/gateway/trust/bundles/{version}.pem", include_in_schema=False)
def get_versioned_trust_bundle(
    request: Request, version: str, publication: TrustPublication = Depends(_publication)
) -> Response:
    """Download the exact immutable bundle whose canonical bytes hash to this version."""
    return _asset(
        request,
        publication.bundles.get(version),
        "application/x-pem-file",
        filename=f"{version}.pem",
        immutable=True,
    )


@router.get("/api/gateway/trust/certificates/{fingerprint}.cer")
@router.head("/api/gateway/trust/certificates/{fingerprint}.cer", include_in_schema=False)
def get_trust_certificate(
    request: Request, fingerprint: str, publication: TrustPublication = Depends(_publication)
) -> Response:
    """Download exactly one DER certificate, never a PEM bundle disguised as .cer."""
    info = next(
        (
            item
            for version in publication.manifest.versions
            for item in version.certificates
            if item.fingerprint_sha256 == fingerprint
        ),
        None,
    )
    filename = (
        f"neurwerk-root-{info.not_before.astimezone(UTC):%Y%m%d}-{fingerprint[:8]}.cer"
        if info
        else None
    )
    return _asset(
        request,
        publication.certificates.get(fingerprint),
        "application/pkix-cert",
        filename=filename,
        immutable=True,
    )
