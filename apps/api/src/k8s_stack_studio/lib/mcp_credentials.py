"""Isolated OpenBao KV writes and read-only confirmation of runtime delivery."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.models.mcp import McpRegistration


class McpSetupError(Exception):
    """An allowlisted operation error, never an upstream error body."""

    def __init__(self, code: str) -> None:
        """Expose only a stable code to callers and persisted operation history."""
        super().__init__(code)
        self.code = code


@dataclass(repr=False)
class CredentialRecord:
    """Short-lived secret material; only the version and configured flag may persist."""

    api_key: str = field(repr=False)
    version: str
    operation_id: str
    cas: int


class McpCredentials:
    """Kubernetes-authenticated access to only chart-approved per-integration records."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        """Keep the short-lived OpenBao session in memory only."""
        self.settings = settings
        self.client = client
        self.token = ""
        self.expires = 0.0
        self.lock = asyncio.Lock()

    async def _login(self) -> str:
        async with self.lock:
            if time.monotonic() < self.expires:
                return self.token
            try:
                jwt = Path(self.settings.mcp_openbao_token_file).read_text().strip()
                response = await self.client.post(
                    self.settings.mcp_openbao_url + "/v1/auth/kubernetes/login",
                    json={"role": "studio-mcp", "jwt": jwt},
                )
                response.raise_for_status()
                auth = response.json()["auth"]
                token, duration = auth["client_token"], auth["lease_duration"]
            except (OSError, httpx.HTTPError, ValueError, KeyError, TypeError):
                raise McpSetupError("credential-store-unavailable") from None
            if (
                not isinstance(token, str)
                or not token
                or type(duration) is not int
                or duration <= 0
            ):
                raise McpSetupError("credential-store-unavailable")
            self.token = token
            self.expires = time.monotonic() + max(0, min(duration - 30, 240))
            return token

    async def _request(
        self,
        method: str,
        identity: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # identity is resolved from the verified chart catalog, never a caller path.
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", identity):
            raise McpSetupError("invalid-credential-policy")
        token = await self._login()
        try:
            response = await self.client.request(
                method,
                self.settings.mcp_openbao_url + f"/v1/secret/data/mcp/shared/{identity}",
                headers={"X-Vault-Token": token},
                json=body,
            )
            if response.status_code == 403:
                self.expires = 0
            response.raise_for_status()
            data = response.json()["data"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise McpSetupError("credential-store-unavailable") from None
        if not isinstance(data, dict):
            raise McpSetupError("credential-store-unavailable")
        return data

    async def read(self, identity: str) -> CredentialRecord:
        """Read one isolated record; a missing record requires approved reconciliation."""
        value = await self._request("GET", identity)
        try:
            data, version = value["data"], value["metadata"]["version"]
            invalid = (
                set(data) != {"apiKey", "version", "operationId", "kvVersion"}
                or not isinstance(data["apiKey"], str)
                or not re.fullmatch(r"initial|[a-f0-9]{32}", data["version"])
                or not isinstance(data["operationId"], str)
                or type(version) is not int
                or version != data["kvVersion"]
                or version < 1
            )
        except (ValueError, TypeError, KeyError):
            raise McpSetupError("invalid-credential-record") from None
        if invalid:
            raise McpSetupError("invalid-credential-record")
        return CredentialRecord(data["apiKey"], data["version"], data["operationId"], version)

    async def write(self, identity: str, operation_id: str, key: str) -> None:
        """Use CAS and the operation ID to make response-loss retries unambiguous."""
        current = await self.read(identity)
        if current.operation_id == operation_id:
            return
        version = operation_id.replace("-", "")
        result = await self._request(
            "POST",
            identity,
            {
                "options": {"cas": current.cas},
                "data": {
                    "apiKey": key,
                    "version": version,
                    "operationId": operation_id,
                    "kvVersion": current.cas + 1,
                },
            },
        )
        if result.get("version") != current.cas + 1:
            raise McpSetupError("credential-write-unconfirmed")


def forward_backend(identity: str, version: str) -> str:
    """Match the chart's versioned backend name without disclosing a credential digest."""
    return f"mcp-forward-{hashlib.sha256(identity.encode()).hexdigest()[:12]}-{version}"


def _secret_name(identity: str, version: str) -> str:
    return f"mcp-key-{hashlib.sha256(identity.encode()).hexdigest()[:12]}-{version}"


def _forward_route(config: dict[str, Any], item: McpRegistration, expected: str) -> bool:
    """Read v1.6.0 DumpBind/DumpListener/RouteSet, not a recursive name search."""
    for bind in config["binds"]:
        if bind["mode"] != "standard" or not bind["address"].endswith(":8080"):
            continue
        for listener in bind["listeners"].values():
            if (
                listener["gatewayName"],
                listener["gatewayNamespace"],
                listener["listenerName"],
                listener["protocol"],
            ) != (
                "contextforge-providers",
                "infra-agentgateway",
                "providers",
                "HTTP",
            ):
                continue
            for route in listener.get("routes", {}).values():
                if (route["namespace"], route["name"]) == (
                    "infra-agentgateway",
                    "mcp-forward-" + item.id,
                ):
                    return _route_ready(route, item, expected)
    return False


def _route_ready(route: dict[str, Any], item: McpRegistration, expected: str) -> bool:
    if item.credential is None:
        return False
    policies = {
        key: value for policy in route.get("inlinePolicies", []) for key, value in policy.items()
    }
    remove = policies.get("requestHeaderModifier", {}).get("remove", [])
    backends = route.get("backends", [])
    return (
        route.get("matches") == [{"path": {"exact": "/" + item.id}}]
        and len(backends) == 1
        and backends[0].get("backend") == "infra-agentgateway/" + expected
        and backends[0].get("weight", 1) > 0
        and not backends[0].get("inlinePolicies")
        and {
            "authorization",
            "cookie",
            "x-contextforge-account-email",
            item.credential.header.lower(),
        }
        <= {name.lower() for name in remove}
    )


def _forward_config(
    config: dict[str, Any], item: McpRegistration, record: CredentialRecord
) -> bool:
    # Source: agentgateway v1.6.0 store/binds.rs, types/agent.rs and http/auth/mod.rs.
    # BackendAuth credentials use a redacted key. The versioned backend plus the
    # controller's Accepted reason below proves that its Secret resolved, not an
    # empty fail-closed placeholder. No dump content is logged or returned.
    expected = forward_backend(item.id, record.version)
    upstream = urlsplit(item.upstream_url)
    backends = [
        backend
        for backend in config["backends"]
        if backend.get("backend", {}).get("host")
        == {
            "name": expected,
            "namespace": "infra-agentgateway",
            "target": f"{upstream.hostname}:443",
        }
    ]
    if len(backends) != 1 or item.credential is None:
        return False
    policies = backends[0].get("inlinePolicies", [])
    auth = [policy["backendAuth"] for policy in policies if "backendAuth" in policy]
    expected_auth = (
        [
            {
                "credentials": [
                    {
                        "location": {"header": {"name": item.credential.header.lower()}},
                        "key": "<redacted>",
                    }
                ]
            }
        ]
        if record.api_key
        else []
    )
    return (
        not config.get("policies")
        and auth == expected_auth
        and _forward_route(config, item, expected)
    )


def _backend_accepted(
    backend: dict[str, Any],
    item: McpRegistration,
    record: CredentialRecord,
) -> bool:
    if item.credential is None:
        return False
    metadata, spec = backend["metadata"], backend["spec"]
    expected_auth = (
        {
            "credentials": [
                {
                    "secretRef": {"name": _secret_name(item.id, record.version), "key": "apiKey"},
                    "location": {"header": {"name": item.credential.header}},
                }
            ]
        }
        if record.api_key
        else None
    )
    return (
        metadata["name"] == forward_backend(item.id, record.version)
        and metadata["namespace"] == "infra-agentgateway"
        and spec["static"] == {"host": urlsplit(item.upstream_url).hostname, "port": 443}
        and spec["policies"].get("auth") == expected_auth
        and any(
            condition.get("type") == "Accepted"
            and condition.get("status") == "True"
            and condition.get("reason") == "Accepted"
            and condition.get("observedGeneration") == metadata["generation"]
            for condition in backend.get("status", {}).get("conditions", [])
        )
    )


class McpActivation:
    """Observe ESO/Flux results; Studio cannot change Kubernetes workloads or read Secrets."""

    def __init__(
        self,
        settings: Settings,
        kube: httpx.AsyncClient,
        gateway: httpx.AsyncClient,
    ) -> None:
        """Use separate TLS-verified transports and projected short-lived identity."""
        self.settings, self.kube, self.gateway = settings, kube, gateway

    async def _kube_get(self, path: str) -> dict[str, Any]:
        response = await self.kube.get(
            self.settings.mcp_kubernetes_url + path,
            headers={
                "Authorization": "Bearer "
                + Path(self.settings.mcp_kubernetes_token_file).read_text().strip()
            },
        )
        response.raise_for_status()
        return response.json()

    async def _deployment_ready(self, identity: str, version: str, configured: bool) -> bool:
        try:
            deployment = await self._kube_get(
                f"/apis/apps/v1/namespaces/infra-agentgateway/deployments/mcp-{identity}-deploy",
            )
            spec, status = deployment["spec"], deployment.get("status", {})
            expected = spec["replicas"]
            environments = [
                container.get("env", [])
                for container in spec["template"]["spec"]["containers"]
                if container["name"] == "mcp-" + identity
            ]
            if len(environments) != 1:
                return False
            environment = environments[0]
            refs = [env for env in environment if env.get("valueFrom", {}).get("secretKeyRef")]
            # The chart allows one apiKey reference. For the shipped Brave
            # consumer, confirm that it feeds the variable the process reads.
            if (
                len(refs) != 1
                or len({env["name"] for env in environment}) != len(environment)
                or (identity == "brave" and refs[0]["name"] != "BRAVE_API_KEY")
            ):
                return False
            return (
                spec["template"]["metadata"]["annotations"].get("mcp.neurwerk.com/key-version")
                == version
                and (expected > 0 if configured else expected == 0)
                and refs[0]["valueFrom"]["secretKeyRef"]
                == {"name": _secret_name(identity, version), "key": "apiKey"}
                and status.get("observedGeneration", 0) >= deployment["metadata"]["generation"]
                and all(
                    status.get(key, 0) == expected
                    for key in (
                        "replicas",
                        "updatedReplicas",
                        "readyReplicas",
                        "availableReplicas",
                    )
                )
            )
        except (OSError, httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError):
            return False

    async def _forward_ready(self, item: McpRegistration, record: CredentialRecord) -> bool:
        try:
            expected = forward_backend(item.id, record.version)
            backend = await self._kube_get(
                "/apis/agentgateway.dev/v1alpha1/namespaces/infra-agentgateway/"
                + "agentgatewaybackends/"
                + expected,
            )
            if not _backend_accepted(backend, item, record):
                return False
            response = await self.gateway.get(self.settings.mcp_provider_admin_url + "/config_dump")
            response.raise_for_status()
            ready = _forward_config(response.json(), item, record)
        except (OSError, httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            return False
        return ready

    async def wait(self, item: McpRegistration, record: CredentialRecord) -> None:
        """Wait for the exact consumer generation, not merely an OpenBao write or ESO sync."""
        if item.credential is None:
            raise McpSetupError("invalid-credential-policy")
        async with asyncio.timeout(540):
            while True:
                if item.credential.method == "upstream-env":
                    ready = await self._deployment_ready(
                        item.id, record.version, bool(record.api_key)
                    )
                elif item.credential.method == "gateway-header":
                    ready = await self._forward_ready(item, record)
                else:
                    raise McpSetupError("invalid-credential-policy")
                if ready:
                    return
                await asyncio.sleep(3)
