"""Create isolated, ignored development secrets and a local workload CA once."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import ssl
import subprocess
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
secrets_dir = root / ".dev-local"
secrets_dir.mkdir(mode=0o700, exist_ok=True)
(secrets_dir / "demo-users").mkdir(mode=0o700, exist_ok=True)
env_file = secrets_dir / "credentials.env"
if not env_file.exists():
    credentials = (
        "KEYCLOAK_DB_PASSWORD",
        "KEYCLOAK_ADMIN_PASSWORD",
        "DEV_USER_PASSWORD",
        "BRIDGE_CLIENT_SECRET",
        "STUDIO_LOGS_PASSWORD",
    )
    descriptor = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("# Local-only credentials; keep with the Compose data volumes.\n")
        for name in credentials:
            stream.write(f"{name}={secrets.token_hex(24)}\n")
    print("Created .dev-local/credentials.env")

tls = secrets_dir / "tls"
tls.mkdir(mode=0o700, exist_ok=True)
required = ("ca.crt", "ca.key", "server.crt", "server.key", "studio.crt", "studio.key")
if not all((tls / name).exists() for name in required):
    if any((tls / name).exists() for name in required):
        raise SystemExit(
            "Incomplete local TLS material. Restore it or move .dev-local/tls aside."
        )

    def openssl(*args: str) -> None:
        subprocess.run(
            ["openssl", *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    ca = tls / "ca.crt"
    ca_key = tls / "ca.key"
    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-noenc",
        "-days",
        "3650",
        "-subj",
        "/CN=Studio local development CA",
        "-keyout",
        str(ca_key),
        "-out",
        str(ca),
    )
    for name, common_name, extensions in (
        (
            "server",
            "pii-sim",
            "subjectAltName=DNS:pii-sim,DNS:logs-sim\nextendedKeyUsage=serverAuth\n",
        ),
        ("studio", "frontend-studio-api", "extendedKeyUsage=clientAuth\n"),
    ):
        key = tls / f"{name}.key"
        request = tls / f"{name}.csr"
        extension_file = tls / f"{name}.ext"
        extension_file.write_text(extensions)
        openssl(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-noenc",
            "-subj",
            f"/CN={common_name}",
            "-keyout",
            str(key),
            "-out",
            str(request),
        )
        openssl(
            "x509",
            "-req",
            "-in",
            str(request),
            "-CA",
            str(ca),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-days",
            "3650",
            "-out",
            str(tls / f"{name}.crt"),
            "-extfile",
            str(extension_file),
        )
        request.unlink()
        extension_file.unlink()
        key.chmod(0o600)
    ca_key.chmod(0o600)
    print("Created local CA and workload certificates in .dev-local/tls")

# The local developer can view every demo destination through the real API.
catalog = json.loads((root / "dev/gateway-catalog.json").read_text())
permissions = set()
for group in (
    "self-hosted-api-providers",
    "external-api-providers",
    "external-subscription-providers",
    "mcp-servers",
):
    for entry in catalog[group]:
        for destination in entry["destinations"]:
            permissions.update(destination["required_permissions"])
            for mode in destination["credential_modes"]:
                permissions.update(mode["required_permissions"])
(secrets_dir / "demo-users/gateway-roles.txt").write_text(
    "\n".join(sorted(permissions)) + "\n"
)

# Public download preview only: a separate demo root, with its key discarded.
gateway = secrets_dir / "gateway"
gateway.mkdir(mode=0o700, exist_ok=True)
inspection_root = gateway / "inspection-root.pem"
if not inspection_root.exists():
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-noenc",
            "-days", "3650", "-subj", "/CN=Studio demo inspection root - not for real traffic",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:1",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", os.devnull, "-out", str(inspection_root),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
pem = inspection_root.read_text()
version = hashlib.sha256(pem.encode("ascii")).hexdigest()
(gateway / "snapshots.json").write_text(json.dumps({
    "schema_version": 1,
    "current_version": version,
    "versions": [{
        "version": version,
        "bundle_sha256": version,
        "published_at": datetime.fromtimestamp(inspection_root.stat().st_mtime, UTC).isoformat(),
        "certificates": [{
            "fingerprint_sha256": hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest(),
            "pem": pem,
            "purpose": "inspection-root",
            "state": "active",
        }],
    }],
}, indent=2) + "\n")
