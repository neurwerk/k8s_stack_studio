"""Trust downloads are atomic, root-only, content-addressed and narrowly public."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi_keycloak_middleware.keycloak_backend import KeycloakBackend

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.controllers.gateway import router
from k8s_stack_studio.lib.auth import configure_auth
from k8s_stack_studio.lib.dependencies import get_settings
from k8s_stack_studio.lib.gateway_files import MAX_DOCUMENT_BYTES, GatewayUnavailableError
from k8s_stack_studio.lib.gateway_trust import trust_publication


def certificate(name, *, ca=True, intermediate=False, wrong_signature=False, expired=False):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, name)])
    issuer = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "issuer")])
    now = datetime.now(UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer if intermediate else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(now + timedelta(days=-1 if expired else 90))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(ec.generate_private_key(ec.SECP256R1()) if wrong_signature else key, hashes.SHA256())
    )


def snapshot(*certificates):
    bundle = b"".join(item.public_bytes(serialization.Encoding.PEM) for item in certificates)
    digest = hashlib.sha256(bundle).hexdigest()
    return {
        "version": digest,
        "bundle_sha256": digest,
        "published_at": datetime.now(UTC).isoformat(),
        "certificates": [
            {
                "fingerprint_sha256": item.fingerprint(hashes.SHA256()).hex(),
                "pem": item.public_bytes(serialization.Encoding.PEM).decode(),
                "purpose": "inspection-root",
                "state": "active",
            }
            for item in certificates
        ],
    }


@pytest.fixture
def publication(tmp_path):
    root = certificate("Example inspection root")
    version = snapshot(root)
    data = {"schema_version": 1, "current_version": version["version"], "versions": [version]}
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps(data))
    return Settings(gateway_trust_file=str(path)), path, data, root


async def test_public_get_head_and_authentication_boundaries(publication, monkeypatch):
    settings, _, data, root = publication
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(KeycloakBackend, "_get_public_key", lambda self: None)
    configure_auth(
        app,
        Settings(
            keycloak_server_url="http://kc:8080",
            keycloak_realm="example",
            keycloak_client_id="studio",
        ),
    )
    version = data["current_version"]
    fingerprint = root.fingerprint(hashes.SHA256()).hex()
    prefix = "/api/gateway/trust"
    paths = [
        f"{prefix}/manifest.json",
        f"{prefix}/bundle.pem",
        f"{prefix}/bundles/{version}.pem",
        f"{prefix}/certificates/{fingerprint}.cer",
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        for index, path in enumerate(paths):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == (
                "no-store" if index < 2 else "public, max-age=86400, immutable"
            )
            head = await client.head(path)
            assert head.status_code == 200 and not head.content
            for header in ("content-length", "content-type", "etag", "cache-control"):
                assert head.headers[header] == response.headers[header]
            for method in ("POST", "PUT", "DELETE", "OPTIONS"):
                denied = await client.request(method, path)
                assert denied.status_code == 405
                assert denied.headers["allow"] == "GET, HEAD"
        manifest = (await client.get(paths[0])).json()
        info = manifest["versions"][0]["certificates"][0]
        assert "pem" not in info
        assert datetime.fromisoformat(info["not_after"]) == root.not_valid_after_utc
        assert (await client.get(paths[-1])).content == root.public_bytes(
            serialization.Encoding.DER
        )
        assert hashlib.sha256((await client.get(paths[2])).content).hexdigest() == version
        for path in (
            "/api/gateway",
            "/api/admin/gateway",
            f"{prefix}/manifest.json/",
            f"{prefix}/manifest.json%0A",
            f"{prefix}/bundles/not-a-digest.pem",
            f"{prefix}/certificates/{fingerprint}.cer/extra",
            f"{prefix}/snapshots.json",
        ):
            assert (await client.get(path)).status_code == 401
        missing = await client.get(f"{prefix}/bundles/{'0' * 64}.pem")
        assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"


def test_rotation_retains_assets_and_never_serves_cached_good_after_bad(publication):
    settings, path, data, root = publication
    previous = trust_publication(settings)
    replacement = certificate("Next inspection root")
    new = snapshot(root, replacement)
    new["certificates"][0]["state"] = "transitional"
    data["versions"].append(new)
    data["current_version"] = new["version"]
    path.write_text(json.dumps(data))
    current = trust_publication(settings)
    assert current.manifest.current_version == new["version"]
    assert (
        current.bundles[previous.manifest.current_version]
        == previous.bundles[previous.manifest.current_version]
    )
    assert len(current.certificates) == 2
    assert current.manifest.versions[-1].certificates[0].state == "transitional"
    # A broken retained asset invalidates the entire new publication, including current.
    data["versions"][0]["bundle_sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(GatewayUnavailableError):
        trust_publication(settings)
    path.unlink()
    with pytest.raises(GatewayUnavailableError):
        trust_publication(settings)


@pytest.mark.parametrize("fault", ["intermediate", "leaf", "signature"])
def test_only_verified_self_signed_ca_roots(publication, fault):
    settings, path, _, _ = publication
    version = snapshot(
        certificate(
            "invalid",
            ca=fault != "leaf",
            intermediate=fault == "intermediate",
            wrong_signature=fault == "signature",
        )
    )
    data = {"schema_version": 1, "current_version": version["version"], "versions": [version]}
    path.write_text(json.dumps(data))
    with pytest.raises(GatewayUnavailableError):
        trust_publication(settings)


@pytest.mark.parametrize(
    "fault",
    [
        "private-key",
        "multiple-pem",
        "fingerprint",
        "duplicate-certificate",
        "duplicate-version",
        "wrong-digest",
        "wrong-version",
        "missing-current",
        "schema",
        "oversize",
    ],
)
def test_invalid_publication_is_all_or_nothing(publication, fault):
    settings, path, data, _ = publication
    version = data["versions"][0]
    item = version["certificates"][0]
    if fault == "private-key":
        item["pem"] += "\n-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----\n"
    elif fault == "multiple-pem":
        item["pem"] += item["pem"]
    elif fault == "fingerprint":
        item["fingerprint_sha256"] = "0" * 64
    elif fault == "duplicate-certificate":
        version["certificates"].append(item.copy())
    elif fault == "duplicate-version":
        data["versions"].append(version.copy())
    elif fault == "wrong-digest":
        version["bundle_sha256"] = version["version"] = "0" * 64
        data["current_version"] = "0" * 64
    elif fault == "wrong-version":
        version["version"] = "0" * 64
    elif fault == "missing-current":
        data["current_version"] = "0" * 64
    elif fault == "schema":
        data["schema_version"] = 2
    path.write_text(" " * (MAX_DOCUMENT_BYTES + 1) if fault == "oversize" else json.dumps(data))
    with pytest.raises(GatewayUnavailableError):
        trust_publication(settings)


async def test_missing_projection_has_safe_error(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        gateway_trust_file=str(tmp_path / "private-path.json")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        result = await client.get("/api/gateway/trust/manifest.json")
        assert result.status_code == 503
        assert result.headers["cache-control"] == "no-store"
        assert "private-path" not in result.text


async def test_required_version_gates_readiness_asset_and_all_downloads(publication):
    settings, path, data, root = publication
    staged = snapshot(root, certificate("Next root"))
    settings.gateway_trust_required_version = staged["version"]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    prefix = "/api/gateway/trust"
    paths = [
        f"{prefix}/manifest.json",
        f"{prefix}/bundle.pem",
        f"{prefix}/bundles/{staged['version']}.pem",
        f"{prefix}/certificates/{root.fingerprint(hashes.SHA256()).hex()}.cer",
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for url in paths:
            for method in ("GET", "HEAD"):
                response = await client.request(method, url)
                assert response.status_code == 503
                assert response.headers["cache-control"] == "no-store"
                assert str(path) not in response.text and staged["version"] not in response.text
        data["versions"].append(staged)
        path.write_text(json.dumps(data))
        assert (await client.get(paths[0])).json()["current_version"] == data["current_version"]
        asset = await client.get(paths[2])
        assert asset.status_code == 200
        assert hashlib.sha256(asset.content).hexdigest() == staged["version"]
        data["current_version"] = staged["version"]
        path.write_text(json.dumps(data))
        assert (await client.get(paths[1])).content == asset.content
        path.write_text('{"private": "never-return-this"}')
        response = await client.get(paths[2])
        assert response.status_code == 503 and "never-return-this" not in response.text


def test_retained_expired_roots_are_downloadable_and_floor_format_is_exact(
    publication, monkeypatch
):
    settings, path, data, _ = publication
    expired = certificate("Historical root", expired=True)
    historical = snapshot(expired)
    data["versions"].append(historical)
    path.write_text(json.dumps(data))
    result = trust_publication(settings)
    assert result.manifest.versions[-1].certificates[0].not_after < datetime.now(UTC)
    assert result.bundles[historical["version"]] == expired.public_bytes(serialization.Encoding.PEM)
    for invalid in ("A" * 64, "0" * 63, "0" * 64 + "\n", "secret-payload"):
        monkeypatch.setenv("STUDIO_GATEWAY_TRUST_REQUIRED_VERSION", invalid)
        with pytest.raises(ValueError):
            Settings()
    monkeypatch.setenv("STUDIO_GATEWAY_TRUST_REQUIRED_VERSION", data["current_version"])
    assert Settings().gateway_trust_required_version == data["current_version"]
