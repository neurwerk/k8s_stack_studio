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

## Operator MCP discovery (opt-in)

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
and offers a status-only retry. This does not add upstream schema quarantine or
catalog versioning; follow upstream #7014 and #7021 for those limits.

## Contributing and support

- **Contributions:** Read [CONTRIBUTING.md](.github/CONTRIBUTING.md) before proposing a change.
- **Bug reports and feature requests:** Use [GitHub Issues](https://github.com/neurwerk/k8s_stack_studio/issues) for reproducible bugs and clearly scoped feature requests.

## Security

Report vulnerabilities privately by following the instructions in [SECURITY.md](SECURITY.md).

## Licensing

Project-owned content is licensed under the [MIT License](LICENSE). Third-party content retains its upstream license.
