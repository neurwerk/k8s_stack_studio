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
and `pnpm lint`, `pnpm typecheck`, `pnpm --filter web test:mcp`,
`pnpm --filter web test:gateway`, `pnpm build`.
Set `MCP_SETUP_TEST_DATABASE_URL` to an isolated local PostgreSQL database for the
production-handler/worker tests; each test creates and removes its own schema.
CI supplies PostgreSQL. These tests exercise actual setup handlers, authorization,
native publication and restart/concurrency logic, with external HTTP transports
mocked; they do not use the development preview router.

## AI Gateway presentation

`/gateway` presents the caller's permitted models, MCP integrations and
applications. `/admin/gateway` additionally requires `gateway-admin` and shows
complete configuration plus desired/observed revisions. This visibility role
does not grant invocation or another user's activity. Existing key management
uses the term **Neurwerk access keys**; provider credentials are a separate choice.

Base owns the schema-1 JSON documents mounted read-only using these exact variables:

| Environment variable | Document |
| --- | --- |
| `STUDIO_GATEWAY_CATALOG_FILE` | `catalog.json`: effective endpoints, destinations and operation profiles |
| `STUDIO_GATEWAY_STATUS_FILE` | Optional `status.json`: observed revisions, freshness and health |
| `STUDIO_GATEWAY_TRUST_FILE` | `snapshots.json`: public inspection roots and retained bundles |
| `STUDIO_GATEWAY_TRUST_REQUIRED_VERSION` | Optional exact 64-character lowercase bundle SHA-256 readiness floor |

Paths default to unconfigured. Studio stores no routing database and receives no
signing key. Catalog/status sibling reads resolve a projected volume's `..data`
once. Separate volumes are joined only by matching catalog and policy revisions.
Each read is limited to 1 MiB; the catalog permits 32 endpoints, 500 destinations,
128 profiles, and 64 operations per profile. Destination identities are unique
within their kind; endpoint and profile identities are unique in the catalog.
URLs must be credential-free HTTPS (HTTP is accepted only for exact loopback
development addresses). Required permissions are all-of checks on the verified
AgentGateway grants; credential modes add their own all-of checks. Personal
responses exclude unentitled destinations and all unreferenced configuration
and observations. Both authenticated APIs return `Cache-Control: no-store`.

Status has `schema_version`, `catalog_revision`, `applied_policy_revision`,
`observed_at`, `valid_until`, `endpoints: [{id, state}]`, and
`profiles: [{id, revision, state}]`. States are `available`, `unavailable` or
`unknown`. Missing, invalid, future-dated, expired or mismatched evidence is
unknown; profile health additionally requires its exact revision. Operation
support is a separate declared property, never a promise that arbitrary website
flows are inspected. API failures expose fixed messages, not document contents.

### Public inspection roots

Only exact `GET`/`HEAD` download routes bypass both authentication boundaries:

- `/api/gateway/trust/manifest.json` describes current and retained versions.
- `/api/gateway/trust/bundle.pem` downloads the current PEM bundle.
- `/api/gateway/trust/bundles/<sha256>.pem` downloads a content-addressed bundle.
- `/api/gateway/trust/certificates/<sha256>.cer` downloads one certificate as DER.

The complete publication is validated before any asset is served: one CA root
per PEM field, self-signature, DER fingerprint, unique snapshot versions and
fingerprints, canonical PEM bundle digest, and current-version membership.
Intermediates, leaf certificates and private-key material are rejected. Certificate
validity dates are derived from DER; retained expired roots remain downloadable
and their dates remain visible. A bundle version equals its canonical PEM SHA-256.
The manifest exposes `not_before`/`not_after` and no PEM text or filesystem paths.
Publications are bounded to 64 retained versions and 16 roots per version, within
the 1 MiB document limit. Only one validated document is cached in process, keyed
by its exact bytes; every request reads the current file and a bad update never
falls back to stale good data.

Current manifest/bundle responses use `no-store`; immutable assets use
`public, max-age=86400, immutable`, exact content lengths, SHA-256 ETags and
`nosniff`. Missing publication returns 503; an unknown asset in a valid
publication returns 404. Studio's hostname TLS must be independently trusted.
The publisher must first distribute retained immutable assets to every replica,
then advance the current pointer, retaining former-current versions for at least
31 days or the workstation update window plus one day, whichever is longer.
Certificates remain while any retained version references them. Root retirement
and signer readiness are separate Base operations.

When the optional floor is set, **every trust GET/HEAD returns 503** until the
fully validated snapshot contains that version. No floor preserves existing
startup behavior. Base uses the API container's
`/api/gateway/trust/bundles/<required-version>.pem` as its readiness probe
(initial trust without a floor uses `/api/gateway/trust/bundle.pem`); startup
and liveness remain `/api/version`. The separate management process has no new
settings or health route. Stage retained assets, roll the required-version setting,
verify every serving replica's immutable bundle bytes/digest, then promote current.
503 responses are fixed and `no-store`, with no paths or configuration contents.
Expiration does not invalidate retained downloads. Current-root health is shown
as unavailable when a root is expired or not yet valid; publication, certificate
validity and loaded-signer health remain separate. Retention is not an instruction
to install an expired root.

### Usage and personal activity additions (0.18.0)

Existing usage routes keep their authorization and numeric fields:
`GET /api/users/{user_id}/usage`, `GET /api/users/{user_id}/usage/daily`,
`GET /api/usage/daily` and
`GET /api/usage/people`. Self usage is allowed; other principals and aggregate
usage require `langfuse-admin`. All successful responses are `no-store`.
`POST /api/me/llm-activity` remains opt-in and strictly self-only, even for admins.

All usage query strings and the activity JSON body accept only these optional
classification fields, mapped to the identical `neurwerk.<field>` attribute:

| Field | Accepted values |
| --- | --- |
| `entry_mode` | `api`, `forward_proxy` |
| `destination_kind` | `model`, `mcp`, `application` |
| `provider_credential_source` | `company`, `caller_supplied`, `none` |
| `billing_classification` | `company_api`, `personal_api`, `subscription`, `unknown` |
| `destination_id`, `provider_id`, `binding_id`, `protocol_profile`, `operation_id`, `policy_revision`, `requested_model`, `resolved_model`, `request_id` | One exact nonempty string, at most 255 characters, no whitespace/control characters |

Unknown fields, arbitrary metadata/filter objects and caller-selected identities
are rejected. Calendar routes retain `start`/`end`; activity retains `q`, `type`
(`all`, `llm`, `mcp`) and its paired timestamp bounds. Selected metadata filters
are ANDed as exact equality; missing historical attributes do not match a selected
value, including explicit `unknown` billing. Clear filters to include those rows.
The server always supplies `agentgateway.user` for a user usage route and `userId`
for activity; every activity result is checked against that owner and the filters.

Every period, daily model row and person total adds:

```json
{
  "request_scope": "native_llm_records",
  "accounting": {
    "tokens": {"state": "partial", "reported_sum": 22, "complete_total": null, "known_records": 2, "total_records": 6},
    "cost_usd": {"state": "unknown", "reported_sum": 0, "complete_total": null, "known_records": 0, "total_records": 6}
  }
}
```

`state` is `known` only when all selected native records have that metric's true
completeness flag; a mix is `partial`, otherwise `unknown`. Zero selected records
have known zero totals. `complete_total` is numeric only for `known`;
`reported_sum` retains all native contributions, including reported legacy retry
usage. Existing `requests`, `total_tokens`, `cost_usd` remain native record counts
and reported sums for API compatibility. They are not a distinct logical-request
or attempt ledger. The UI labels reported chart sums separately and shows unknown
or partial totals rather than treating absent cost as free service.

Native summaries group by `neurwerk.token_usage_known` and `neurwerk.cost_known`
alongside model or user dimensions. Native PostgreSQL encodes grouped boolean
attributes as `"true"`/`"false"`; JSON booleans are also accepted. Missing historical
flags remain unknown regardless of coalesced numeric sums. These flags must be
computed by the producer from final native field presence, not aggregate zeros.
The initial version-5 path has one attempt; completeness covers selected native
records, not all retries or a provider invoice. Generic applications/CONNECT and
MCP are not added to native LLM accounting without a supported producer.

Each activity item adds `gateway`, containing the above normalized fields plus
nullable boolean `token_usage_known` and `cost_known`, and the same `accounting`
shape for that one observation. Absent/invalid context fields are null, except
`billing_classification`, which defaults to `unknown`. Existing nullable `tokens`
and `costUsd` remain reported values. No billing class is inferred from personal
credentials or Neurwerk key type. A true flag without a reported numeric metric
still cannot produce a complete total.

Langfuse must expose these **top-level observation metadata keys**, using
`langfuse.observation.metadata.neurwerk.<field>` in its OTel mapping. Unmapped
span attributes nested under `attributes` are not a filterable substitute.
Only declared bounded scalar context is returned; credential/header/cookie objects,
arbitrary request metadata and generic `response.body` are excluded. The native
tracing producer supplies sanitized `llm.prompt` and pre-restoration
`llm.completion` for qualified JSON/SSE operations. Generic application activity
remains unavailable; neither an application label nor a CONNECT call is invented
as a generation. Base owns database-attribute and tracing publication wiring.

- **Contributions:** Read [CONTRIBUTING.md](.github/CONTRIBUTING.md) before proposing a change.
- **Bug reports and feature requests:** Use [GitHub Issues](https://github.com/neurwerk/k8s_stack_studio/issues) for reproducible bugs and clearly scoped feature requests.

## Security

Report vulnerabilities privately by following the instructions in [SECURITY.md](SECURITY.md).

## Licensing

Project-owned content is licensed under the [MIT License](LICENSE). Third-party content retains its upstream license.
