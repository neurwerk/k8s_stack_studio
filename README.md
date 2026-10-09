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

## MCP Setup

Studio `0.17.0` provides **Server setup → Refresh tools → select → Publish** at
`/admin/mcp`. The API requires both `studio-user` and `mcp-admin`. Charts install
the fixed server IDs, URLs, credential policies and checks. PostgreSQL owns saved
tool selections, confirmed publication and restart-safe operations; the native
virtual servers are owned by `contextforge-studio`.

- **Context7:** optional shared key. Blank replacement keeps the saved key;
  **Remove API key** explicitly removes upstream authentication on Publish.
- **Brave:** required shared key. First Publish the key with no tools, then Refresh,
  select tools and Publish again.
- **GitHub:** each administrator connects their own account before Refresh. Every
  permitted user invokes tools with their own personal OAuth connection.
- **Disable:** clears exact native tool membership and keeps the saved selection.

Refresh also requires a verified email, `llm:invoke`, the selected
`mcp:<id>:invoke` grant and ordinary native account/team rights. Studio leases only
the fixed `gateways.update` discovery role for 120 seconds and calls native refresh
as that person. Revoked accounts and ordinary grants are never repaired. OAuth
tokens remain in ContextForge. Refresh updates native definitions directly; newly
discovered tools stay unselected. A partial failure is reconciled against the last
confirmed publication; unreadable native state is shown as unconfirmed until a
successful Refresh, Publish or Disable.

Shared keys go only to OpenBao `secret/data/mcp/shared/<id>`, with CAS and
`apiKey`, `version`, `operationId`, `kvVersion` fields. ESO/Flux deliver versioned
Secrets. Publish waits for the actual consumer generation and exact native
membership. Brave needs a fully rolled-out Deployment referencing that generation;
Context7 needs the versioned AgentgatewayBackend's current `Accepted=True` /
`reason=Accepted` condition and the matching active route/auth policy in pinned
AgentGateway `v1.6.0`'s private `config_dump`. Studio reads Deployment and backend
status, never Kubernetes Secret values. Dumps, entered keys and upstream errors
are never returned, logged or stored in Studio's database.

Activate with matching Base/Tooling and API/Web versions, the normal database
migration (`k8s-stack-studio-migrate`), and `K8S_STUDIO_MCP_SETUP_ENABLED=true`.
The chart's `mcp.studioSetup.enabled` selects deployment wiring. Its atomic setup
projection includes `setup_mode=studio-v1`, the catalog/hash, fixed team/role IDs
and verified discovery-role readiness. The deployment supplies restricted OpenBao
and Kubernetes identities, TLS trust and the private provider admin endpoint.
This is a clean cutover: any one-time native reset is an explicit operator action;
subsequent bootstrap preserves Studio choices.

Requests carry a revision and operation UUID. Stale/concurrent changes return 409;
identical retries return the existing result. The small API worker resumes Publish
and Disable after restart. Interrupted Refresh reconciles native membership without
reusing an administrator's old discovery admission. A saved key can be retried
without re-entry; input lost before reaching OpenBao must be entered again.

## Contributing and support

### Local MCP UI preview

Run `./start_dev.sh up --detach` from the Studio worktree, then open
`http://localhost:3001/mcp` and sign in as `developer` with the password printed
by the script. `viewer` has ordinary MCP invocation permission but cannot discover
tools; `no-access` cannot enter Studio. Run `uv run --project apps/api --frozen
python dev/smoke.py` to verify the local login and the three MCP models.
Worktrees use separate Compose volumes by default so their generated passwords
do not conflict with the primary checkout. You can override the project name with
`STUDIO_DEV_PROJECT` if needed; only one worktree can bind the default local ports.

The local Compose stack loads `dev/mcp_preview.py` as a **different API entry point**:
it uses the real Studio Keycloak admission and UI, but serves local sample responses
for Context7 (shared, optional key), Brave (shared, required key) and GitHub
(individual connection). The ordinary Studio API entry point and published images
never load this preview. In the main left menu, **MCP Setup** is visible only to the demo MCP
administrator, beside **Users** and **Logs** (which have their own admin roles).
The setup page shows the same server → refresh → select tools → publish/disable
workflow for both key ownership types. The masked key field accepts example text
only; it is discarded on Publish and is never stored in OpenBao or sent to a provider.
Its edits stay in browser memory and never publish or revoke real access. Each person's
Connect and checks remain on
**MCP integrations**; the demo administrator's GitHub connection is personal too.
Expand **Preview scenarios** on MCP Setup to try pending, failed and unavailable
states. Connect opens a local one-time popup. Nothing contacts a real provider,
cluster or customer account; restart the local API to reset sample server state.

External endpoints are deliberately not the default: Brave requires credentials,
Context7 can be rate-limited, and GitHub needs personal consent. The preview is
for interface work, not evidence that a deployed gateway or provider works.

### Validation

Run the complete API lint/format/type/pytest checks from `.github/workflows/quality.yml`
and `pnpm lint`, `pnpm typecheck`, `pnpm --filter web test:mcp`, `pnpm build`.
Set `MCP_SETUP_TEST_DATABASE_URL` to an isolated local PostgreSQL database for the
production-handler/worker tests; each test creates and removes its own schema.
CI supplies PostgreSQL. These tests exercise actual setup handlers, authorization,
native publication and restart/concurrency logic, with external HTTP transports
mocked; they do not use the development preview router.

- **Contributions:** Read [CONTRIBUTING.md](.github/CONTRIBUTING.md) before proposing a change.
- **Bug reports and feature requests:** Use [GitHub Issues](https://github.com/neurwerk/k8s_stack_studio/issues) for reproducible bugs and clearly scoped feature requests.

## Security

Report vulnerabilities privately by following the instructions in [SECURITY.md](SECURITY.md).

## Licensing

Project-owned content is licensed under the [MIT License](LICENSE). Third-party content retains its upstream license.
