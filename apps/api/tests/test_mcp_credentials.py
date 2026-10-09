"""Credential CAS, response-loss recovery and real consumer-generation admission."""

from __future__ import annotations

import copy
from uuid import uuid4

import httpx
import pytest

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.mcp_credentials import (
    CredentialRecord,
    McpActivation,
    McpCredentials,
    McpSetupError,
    forward_backend,
)
from k8s_stack_studio.models.mcp import McpCredential, McpRegistration


async def test_cas_and_lost_response_recovery_keep_secrets_out_of_errors(tmp_path, caplog):
    token_file = tmp_path / "identity"
    token_file.write_text("synthetic-jwt")
    settings = Settings(mcp_openbao_token_file=str(token_file))
    current = {"apiKey": "", "version": "initial", "operationId": "", "kvVersion": 1}
    calls = []
    lose_response = True
    conflict = False

    def bao(request):
        nonlocal lose_response
        import json

        calls.append(request.method)
        if request.url.path == "/v1/auth/kubernetes/login":
            assert json.loads(request.content) == {"role": "studio-mcp", "jwt": "synthetic-jwt"}
            return httpx.Response(
                200, json={"auth": {"client_token": "synthetic-token", "lease_duration": 300}}
            )
        assert request.url.path == "/v1/secret/data/mcp/shared/context7"
        assert request.headers["x-vault-token"] == "synthetic-token"
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": {"data": current.copy(), "metadata": {"version": current["kvVersion"]}}
                },
            )
        payload = json.loads(request.content)
        assert payload["options"] == {"cas": current["kvVersion"]}
        if conflict:
            return httpx.Response(400, text="entered-key synthetic-token")
        current.update(payload["data"])
        if lose_response:
            lose_response = False
            raise httpx.ReadError("entered-key synthetic-token", request=request)
        return httpx.Response(200, json={"data": {"version": current["kvVersion"]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(bao)) as client:
        credentials = McpCredentials(settings, client)
        operation = str(uuid4())
        with pytest.raises(McpSetupError) as failure:
            await credentials.write("context7", operation, "entered-key")
        assert str(failure.value) == "credential-store-unavailable"
        await credentials.write("context7", operation, "ignored-on-retry")
        assert current["apiKey"] == "entered-key" and current["kvVersion"] == 2
        assert calls.count("POST") == 2  # login and one write, despite the lost response
        record = await credentials.read("context7")
        assert "entered-key" not in repr(record)
        conflict = True
        with pytest.raises(McpSetupError):
            await credentials.write("context7", str(uuid4()), "replacement-key")
        assert current["apiKey"] == "entered-key"
        conflict = False
        await credentials.write("context7", str(uuid4()), "")
        assert current["apiKey"] == "" and current["kvVersion"] == 3
        assert all(
            secret not in caplog.text
            for secret in ["entered-key", "synthetic-jwt", "synthetic-token"]
        )


def forwarding(configured=True):
    """Pinned v1.6.0 serde shape, derived from source rather than a recursive sample.

    store/binds.rs Dump{backends,binds}, types/agent.rs BackendWithPolicies,
    RouteBackendTarget, RouteSet, http/auth/mod.rs BackendAuthCredential.
    controller/pkg/agentgateway/utils/utils.go defines the namespace/name BackendKey.
    """
    record = CredentialRecord("test-key" if configured else "", "a" * 32, "test-operation", 2)
    item = McpRegistration(
        id="context7",
        name="Context7",
        authentication_model="no-authentication",
        server_id="server",
        gateway_id="gateway",
        upstream_url="https://mcp.example.test/mcp",
        credential=McpCredential(
            owner="shared", required=False, method="gateway-header", header="CONTEXT7_API_KEY"
        ),
    )
    name = forward_backend(item.id, record.version)
    backend = {
        "backend": {
            "host": {
                "name": name,
                "namespace": "infra-agentgateway",
                "target": "mcp.example.test:443",
            }
        },
        "inlinePolicies": [
            {
                "backendAuth": {
                    "credentials": [
                        {
                            "location": {"header": {"name": "context7_api_key"}},
                            "key": "<redacted>",
                        }
                    ]
                }
            }
        ]
        if configured
        else [],
    }
    route = {
        "key": "route-key",
        "name": "mcp-forward-context7",
        "namespace": "infra-agentgateway",
        "matches": [{"path": {"exact": "/context7"}}],
        "backends": [{"backend": "infra-agentgateway/" + name, "weight": 1}],
        "inlinePolicies": [
            {
                "requestHeaderModifier": {
                    "remove": [
                        "authorization",
                        "cookie",
                        "x-contextforge-account-email",
                        "context7_api_key",
                    ]
                }
            }
        ],
    }
    config = {
        "backends": [backend],
        "policies": [],
        "binds": [
            {
                "address": "0.0.0.0:8080",
                "mode": "standard",
                "listeners": {
                    "listener-key": {
                        "gatewayName": "contextforge-providers",
                        "gatewayNamespace": "infra-agentgateway",
                        "listenerName": "providers",
                        "protocol": "HTTP",
                        "routes": {"route-key": route},
                    }
                },
            }
        ],
    }
    resource = {
        "metadata": {"name": name, "namespace": "infra-agentgateway", "generation": 1},
        "spec": {"static": {"host": "mcp.example.test", "port": 443}, "policies": {}},
        "status": {
            "conditions": [
                {
                    "type": "Accepted",
                    "status": "True",
                    "reason": "Accepted",
                    "observedGeneration": 1,
                }
            ]
        },
    }
    if configured:
        resource["spec"]["policies"]["auth"] = {
            "credentials": [
                {
                    "secretRef": {
                        "name": name.replace("mcp-forward-", "mcp-key-"),
                        "key": "apiKey",
                    },
                    "location": {"header": {"name": "CONTEXT7_API_KEY"}},
                }
            ]
        }
    return item, record, config, resource


@pytest.mark.parametrize("configured", [True, False])
async def test_forward_activation_requires_generation_route_and_exact_auth(
    tmp_path, configured, caplog
):
    item, record, correct, resource = forwarding(configured)
    dump = copy.deepcopy(correct)
    token = tmp_path / "identity"
    token.write_text("synthetic-kubernetes-token")
    settings = Settings(mcp_kubernetes_token_file=str(token))

    def kube(request):
        assert request.url.path.endswith(
            "/agentgatewaybackends/" + forward_backend(item.id, record.version)
        )
        return httpx.Response(200, json=resource)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(kube)) as kube_client,
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=dump)),
        ) as gateway,
    ):
        activation = McpActivation(settings, kube_client, gateway)
        assert await activation._forward_ready(item, record)
        dump = {"unrelated": forward_backend(item.id, record.version)}
        assert not await activation._forward_ready(item, record)
        for missing in ("backends", "binds"):
            dump = copy.deepcopy(correct)
            dump[missing] = []
            assert not await activation._forward_ready(item, record)
        for field, value in [
            ("backends", [{"backend": "infra-agentgateway/wrong-generation"}]),
            ("matches", [{"path": {"exact": "/another-provider"}}]),
            ("inlinePolicies", []),
        ]:
            dump = copy.deepcopy(correct)
            dump["binds"][0]["listeners"]["listener-key"]["routes"]["route-key"][field] = value
            assert not await activation._forward_ready(item, record)
        dump = copy.deepcopy(correct)
        dump["backends"][0]["inlinePolicies"] = forwarding(not configured)[2]["backends"][0][
            "inlinePolicies"
        ]
        assert not await activation._forward_ready(item, record)
        if configured:
            dump = copy.deepcopy(correct)
            dump["backends"][0]["inlinePolicies"][0]["backendAuth"]["credentials"][0]["location"][
                "header"
            ]["name"] = "wrong-header"
            assert not await activation._forward_ready(item, record)
        dump = copy.deepcopy(correct)
        # v1.6.0 emits Accepted=True/PartiallyValid with empty auth on unresolved Secrets.
        condition = resource["status"]["conditions"][0]
        condition["reason"] = "PartiallyValid"
        assert not await activation._forward_ready(item, record)
        condition["reason"] = "Accepted"
        condition["observedGeneration"] = 0
        assert not await activation._forward_ready(item, record)
        assert "test-key" not in caplog.text and "synthetic-kubernetes-token" not in caplog.text


async def test_deployment_activation_requires_versioned_secret_and_complete_rollout(tmp_path):
    identity, version = "brave", "b" * 32
    token = tmp_path / "identity"
    token.write_text("synthetic-token")
    deployment = {
        "metadata": {"generation": 2},
        "spec": {
            "replicas": 1,
            "template": {
                "metadata": {"annotations": {"mcp.neurwerk.com/key-version": version}},
                "spec": {
                    "containers": [
                        {
                            "name": "mcp-brave",
                            "env": [
                                {
                                    "name": "BRAVE_API_KEY",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": forward_backend(identity, version).replace(
                                                "mcp-forward-", "mcp-key-"
                                            ),
                                            "key": "apiKey",
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                },
            },
        },
        "status": {
            "observedGeneration": 2,
            "replicas": 1,
            "updatedReplicas": 1,
            "readyReplicas": 1,
            "availableReplicas": 1,
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=deployment))
    ) as client:
        activation = McpActivation(Settings(mcp_kubernetes_token_file=str(token)), client, client)
        assert await activation._deployment_ready(identity, version, True)
        environment = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        environment[0]["name"] = "UNUSED_API_KEY"
        assert not await activation._deployment_ready(identity, version, True)
        environment[0]["name"] = "BRAVE_API_KEY"
        environment.append({"name": "BRAVE_API_KEY", "value": "stale-key"})
        assert not await activation._deployment_ready(identity, version, True)
        environment.pop()
        for field, value in [
            ("observedGeneration", 1),
            ("updatedReplicas", 0),
            ("replicas", 2),
            ("availableReplicas", 0),
        ]:
            old = deployment["status"][field]
            deployment["status"][field] = value
            assert not await activation._deployment_ready(identity, version, True)
            deployment["status"][field] = old
        deployment["spec"]["template"]["spec"]["containers"][0]["env"][0]["valueFrom"][
            "secretKeyRef"
        ]["name"] = "old-secret"
        assert not await activation._deployment_ready(identity, version, True)
