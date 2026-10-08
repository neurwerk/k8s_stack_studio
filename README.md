# neurwerk.base - Studio

Studio is the web dashboard and API for operating AI platform services in neurwerk.base. See the [neurwerk.base website](https://base.neurwerk.com/) for more information.

| Repository | Description |
| --- | --- |
| [Base chart](https://github.com/neurwerk/k8s_stack_base) | Shared platform charts and release packages that form the foundation of the stack. |
| [Studio](https://github.com/neurwerk/k8s_stack_studio) | Web dashboard and API for operating AI platform services (**this repo**). |
| [Tooling](https://github.com/neurwerk/k8s_stack_tooling) | One container image plus separate CLI tools for setup and operations. |
| [PII Engine](https://github.com/neurwerk/k8s_stack_pii_engine) | Service that uses Presidio to evaluate PII and apply safety policies. |
| [AgentGateway External Processor](https://github.com/neurwerk/k8s_stack_agentgateway_extproc) | Adapter that processes gateway requests and responses with the PII Engine. |
| [Keycloak API Key Bridge](https://github.com/neurwerk/k8s_stack_keycloak_api_key_bridge) | Separate service that issues and validates API keys using Keycloak permissions. |
| [Keycloak Theme](https://github.com/neurwerk/k8s_stack_keycloak_theme) | Customized Keycloak login pages and emails. |
|  |  |
| [Example client chart](https://github.com/neurwerk/k8s_stack_client_example_com) | Reference client configuration and Flux deployment setup to adapt for a new client. |
|  |  |
| [Dify Add-on](https://github.com/neurwerk/k8s_stack_addon_dify) | Optional Dify package with API and web customizations, including single-workspace enforcement. |

## MCP administrator discovery (opt-in)

Enable `K8S_STUDIO_CONTEXTFORGE_ADMIN_DISCOVERY_ENABLED=true` with the compatible
Base `adminDiscovery` setup and read-only publication projection. Any signed-in
`studio-user` with the verified `mcp-admin` realm role, verified email, `llm:invoke`
and the selected `mcp:<id>:invoke` grant can explicitly choose **Discover tools**.
No named username, dedicated discovery login or provider-token sharing is needed.

Studio checks the caller's existing active, verified, non-admin ContextForge
account and fixed-team invocation membership. It then leases the verified
`contextforge-tool-discovery` team role (`gateways.update` only) to that caller
through the existing provisioning API, expiring after 120 seconds. It validates
scope, grantor and expiration before refreshing only the approved gateway as the
caller. Connect and status/tool checks never grant or renew discovery authority.
An almost-expired grant returns a bounded retry time; an expired grant can be
renewed only by a new authorized discovery request. No background refresh or
first-user/fallback-user selection occurs. The service identity receives no
discovery permission and never reads provider tokens.

Keycloak's `mcp-admin` role is the authority for explicit discovery renewals;
removing it blocks the next request with refreshed claims, while already issued
JWTs retain their normal lifetime. Native grants expire independently; disable
the native account or its invocation membership to block all native admission.
This mode intentionally permits reissuing the short-lived discovery grant, but
never restores disabled accounts, membership, or ordinary invocation grants.
Native management must remain private: `gateways.update` is broader than refresh,
and Studio exposes only the fixed refresh action, not an arbitrary API proxy.

Publication still uses the separate Base setup Job, followed by reviewed route
activation. Existing shared tools do not depend on the discovering user's token
for other users' invocations. Disconnection does not delete the catalog; another
authorized administrator can later explicitly refresh with their own connection.
Native refresh itself can mutate shared tool records before publication, so
failed refresh does not guarantee that the prior native catalog is unchanged.

This source change needs a new Studio image release and Base adoption before use.
The old named-person mode below remains available for explicit migration and
cannot be enabled together with administrator discovery.

### Legacy named operator discovery

Personal Connect continues to use ContextForge's existing popup callback. The
separate **Discover tools** action is only for approved individual OAuth integrations
and requires the explicitly bound, verified Studio
operator and exact non-admin native invocation roles plus the fixed team-scoped
discovery role with only `gateways.update`. Studio never grants or repairs these
operator privileges. Base's setup audit checks dormant native grants that upstream
role APIs do not expose.

API configuration uses the `K8S_STUDIO_CONTEXTFORGE_` prefix:

| Setting | Default |
| --- | --- |
| `OPERATOR_DISCOVERY_ENABLED` | `false` |
| `OPERATOR_EMAIL` | empty |
| `OPERATOR_SUBJECT` | empty |
| `OPERATOR_ROLE_NAME` | `neurwerk-mcp-discovery` |
| `PUBLICATION_STATUS_PATH` | empty |

When configured, the status path points to
`/var/run/contextforge-setup/publication.json` in a read-only directory projection
of the existing setup ConfigMap. Studio reads `studio.json`, `publication.json`, `catalog_hash`, the
existing team/role binding keys, and the operator binding keys from one atomic
projection generation, requiring the publication hash to equal the well-formed
live `catalog_hash` and validating matching integration IDs.
Unverified registrations may be absent, including an entirely empty initial
catalog. Retained operator role IDs without matching email/subject bindings are
revocation history, never admission. Studio reloads tool mappings without an API restart;
missing or inconsistent metadata is unavailable, not stale readiness. Deployments
without this path retain their environment-only catalog.

Discovery calls only the selected native gateway with the operator's verified
email; ContextForge uses that account's own saved provider connection. No provider
token reaches Studio or the browser. Successful discovery is not publication:
the operator independently reruns the existing Base setup publication Job. Studio
only polls safe per-integration status, approximately every five seconds for up
to two minutes, and never runs Kubernetes Jobs. Publication `checked_at` is Base's
conservative verification start time and must be strictly later than Discover
completion to prove a fresh publication. Timeout leaves publication pending
and offers a status-only retry. The affected tool list is invalidated immediately
after Discover and refreshed again after publication; newer catalog status
supersedes older local polling results. This does not add upstream schema quarantine or
catalog versioning; follow upstream #7014 and #7021 for those limits.

## Contributing and support

- **Contributions:** Read [CONTRIBUTING.md](.github/CONTRIBUTING.md) before proposing a change.
- **Bug reports and feature requests:** Use [GitHub Issues](https://github.com/neurwerk/k8s_stack_studio/issues) for reproducible bugs and clearly scoped feature requests.

## Security

Report vulnerabilities privately by following the instructions in [SECURITY.md](SECURITY.md).

## Licensing

Project-owned content is licensed under the [MIT License](LICENSE). Third-party content retains its upstream license.
