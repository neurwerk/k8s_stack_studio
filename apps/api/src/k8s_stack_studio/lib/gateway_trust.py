"""Validate all public roots before exposing any content-addressed trust asset."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.gateway_files import (
    GatewayUnavailableError,
    projected_path,
    read_document,
)
from k8s_stack_studio.models.gateway_trust import (
    TrustCertificate,
    TrustCertificateInfo,
    TrustManifest,
    TrustSnapshots,
    TrustVersionInfo,
)

# One shared allowlist for JWT exclusion and Studio's method-aware admission.
TRUST_PUBLIC_PATTERNS = (
    r"^/api/gateway/trust/manifest\.json\Z",
    r"^/api/gateway/trust/bundle\.pem\Z",
    r"^/api/gateway/trust/bundles/[a-f0-9]{64}\.pem\Z",
    r"^/api/gateway/trust/certificates/[a-f0-9]{64}\.cer\Z",
)


def is_public_trust_path(path: str) -> bool:
    """Match exact asset paths, never a directory prefix or arbitrary filename."""
    return any(re.fullmatch(pattern, path) for pattern in TRUST_PUBLIC_PATTERNS)


@dataclass(frozen=True)
class TrustPublication:
    """One fully validated publication, cached only while its bytes are identical."""

    manifest: TrustManifest
    bundles: dict[str, bytes]
    certificates: dict[str, bytes]


def _root(item: TrustCertificate) -> tuple[x509.Certificate, bytes]:
    pem = item.pem.encode("ascii")
    if not re.fullmatch(
        rb"\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*", pem
    ):
        raise GatewayUnavailableError
    certificate = x509.load_pem_x509_certificate(pem)
    if (
        not certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
        or certificate.subject != certificate.issuer
        or certificate.fingerprint(hashes.SHA256()).hex() != item.fingerprint_sha256
    ):
        raise GatewayUnavailableError
    certificate.verify_directly_issued_by(certificate)
    # BasicConstraints is required; a present KeyUsage must also permit signing.
    try:
        usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        pass
    else:
        if not usage.key_cert_sign:
            raise GatewayUnavailableError
    return certificate, certificate.public_bytes(serialization.Encoding.DER)


@lru_cache(maxsize=1)
def _validate(data: bytes) -> TrustPublication:
    """Cache at most one bounded, successful document; never fall back on errors."""
    snapshots = TrustSnapshots.model_validate_json(data)
    bundles: dict[str, bytes] = {}
    certificates: dict[str, bytes] = {}
    versions: list[TrustVersionInfo] = []
    for snapshot in snapshots.versions:
        if snapshot.version in bundles or snapshot.version != snapshot.bundle_sha256:
            raise GatewayUnavailableError
        parts: list[bytes] = []
        infos: list[TrustCertificateInfo] = []
        seen: set[str] = set()
        for item in snapshot.certificates:
            if item.fingerprint_sha256 in seen:
                raise GatewayUnavailableError
            seen.add(item.fingerprint_sha256)
            certificate, der = _root(item)
            previous = certificates.setdefault(item.fingerprint_sha256, der)
            if previous != der:
                raise GatewayUnavailableError
            parts.append(certificate.public_bytes(serialization.Encoding.PEM))
            infos.append(
                TrustCertificateInfo(
                    fingerprint_sha256=item.fingerprint_sha256,
                    purpose=item.purpose,
                    state=item.state,
                    not_before=certificate.not_valid_before_utc,
                    not_after=certificate.not_valid_after_utc,
                )
            )
        bundle = b"".join(parts)
        if hashlib.sha256(bundle).hexdigest() != snapshot.bundle_sha256:
            raise GatewayUnavailableError
        bundles[snapshot.version] = bundle
        versions.append(
            TrustVersionInfo(
                version=snapshot.version,
                published_at=snapshot.published_at,
                bundle_sha256=snapshot.bundle_sha256,
                certificates=infos,
            )
        )
    if snapshots.current_version not in bundles:
        raise GatewayUnavailableError
    return TrustPublication(
        manifest=TrustManifest(current_version=snapshots.current_version, versions=versions),
        bundles=bundles,
        certificates=certificates,
    )


def trust_publication(settings: Settings) -> TrustPublication:
    """Read one complete projected document; validate retained assets as well as current."""
    try:
        publication = _validate(read_document(projected_path(settings.gateway_trust_file, {})))
    except (
        OSError,
        ValueError,
        TypeError,
        InvalidSignature,
        UnsupportedAlgorithm,
        x509.ExtensionNotFound,
        x509.DuplicateExtension,
        GatewayUnavailableError,
    ):
        raise GatewayUnavailableError from None
    required = settings.gateway_trust_required_version
    if required and required not in publication.bundles:
        raise GatewayUnavailableError
    return publication
