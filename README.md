# neurwerk studio

neurwerk studio is a web dashboard and authenticated API for operating AI
platform services. It provides policy inspection and testing, log search, user
and OIDC-client administration, API-key management, and per-user usage views.

The repository is a pnpm/Turbo monorepo containing:

- `apps/web`: Next.js 16 and React 19 frontend.
- `apps/api`: FastAPI backend managed with uv.

## Log links

Logs require `studio-user` and `opensearch-admin`. Studio queries OpenSearch with
the read-only `studio-logs-read` identity over verified TLS; browsers never
connect directly to OpenSearch.

`GET /api/logs` supports `q`, `namespace`, `pod`, `level`, `failure_type`, `size`,
`index`, and optional paired timezone-aware `start`/`end` timestamps. Log level
and failure type are exact collector-owned filters; invalid values return 422.
Older entries without collector metadata return `UNKNOWN` and no failure type.
Time bounds are inclusive, normalized to UTC, and require `start < end`;
malformed or incomplete ranges return 422. Omitting both preserves the existing
newest-first search, with no maximum span.

Alert links use `/logs?namespace=example&at=1790022537`: the UI-only Unix-seconds
shortcut selects exactly ten minutes before through five minutes after the event,
even when opened later. Shareable searches use `namespace`, `pod`, `q`, `level`,
`failure_type`, `start`, and `end` (RFC3339); valid explicit bounds override
`at`. Invalid time links display an error without searching. From/To controls show local time, and Search
writes UTC bounds to the URL and removes `at`. Search starts only after the
verified administrator role is available. Never put raw log entries into links.

## Architecture

The browser loads deployment-specific OIDC settings from `/env.js`. The web app
proxies `/api/*` to the FastAPI service, which validates Keycloak JWTs and
enforces feature-specific realm roles. The API communicates with PII Engine
over workload mTLS and integrates with OpenSearch, Keycloak administration,
the API-key bridge, and AgentGateway's private usage analytics API.

Studio uses the shared `neurwerk-request-segments` package to validate Chat,
Responses, and MCP samples and extract text. Only opaque text segments and
analysis flags cross the Engine boundary through `/v2/studio/analyze-segments`
and `/v2/studio/evaluate-policy`. Studio rebuilds the original request locally
and maps diagnostic segment IDs back to browser paths. The browser API keeps
its existing request, policy, simulation, and v1 response fields.

Provider controls, including stream options, stay in Studio. Replacements require
the exact original segment IDs and order; blocked replies contain no segments,
and Engine reversal data is rejected. Studio retains its 100,000-character
per-text-field limit. The canonical package is vendored under
`apps/api/vendor/request_segments` for independent builds; see its `ORIGIN.md`
before updating it. The Engine must support the v2 routes before this Studio
change is deployed.

Invalid extracted content returns a safe 400; extraction and text-size limits
return 413. Validated Engine v2 limit measurements and correlation IDs are
included in Studio's existing error `detail` string. Studio does not relay raw
Engine error bodies or rejected request values.

Default service URLs in the API settings are intentional Kubernetes service DNS
names. Deployments override identity, credentials, certificates, and any
environment-specific endpoints through `K8S_STUDIO_*` environment variables.

## Personal MCP OAuth

Connect/Reconnect/status supports configured `individual-authentication` entries;
GitHub is an example, not a provider restriction. New compatible providers need
configuration, not Python handlers. No PAT entry, discovery or registration-management
API is exposed. Features default off; publication and deployment are separate.

Configuration is API-only, with prefix `K8S_STUDIO_`:

- `MCP_CATALOG_ENABLED`, `MCP_CATALOG`, `CONTEXTFORGE_TEAM_ID`,
  `CONTEXTFORGE_ACCOUNT_ONBOARDING_ENABLED`, `CONTEXTFORGE_URL`, optional
  `CONTEXTFORGE_CA_CERT`, `CONTEXTFORGE_GLOBAL_ROLE_ID` and `CONTEXTFORGE_TEAM_ROLE_ID`.
- `MCP_CONNECTIONS_ENABLED` enables Connect/status when true. No qualification
  boolean claims to verify encryption or replace runtime controls.
- `CONTEXTFORGE_SERVICE_AUTH_MODE` defaults to `bearer`, preserving standalone
  onboarding with a Secret-backed `CONTEXTFORGE_SERVICE_TOKEN` when native bearer
  authentication is enabled. Personal OAuth requires `trusted-proxy` instead,
  plus `CONTEXTFORGE_SERVICE_ACCOUNT_EMAIL`: a fixed operator-approved native
  service identity. Proxy mode sends **no bearer token or cookie** and does not
  claim token validation. The email is server configuration, never request input.
- `CONTEXTFORGE_OAUTH_STUDIO_ORIGIN` is an exact HTTPS origin without trailing slash.
  `CONTEXTFORGE_OAUTH_CALLBACK_URL` is `/oauth/callback` on that same Studio origin;
  register this exact URL in both native gateway OAuth configuration and the provider app.
- Each individual catalog entry additionally needs `oauth_authorization_origin`:
  a fixed HTTPS provider authorization origin. Native operator-owned gateway
  metadata supplies the authorization/token endpoints and registered client ID.
  Origins use lowercase hosts, omit port 443 and preserve other ports, matching Base.
  Studio checks redirect origin/endpoint, callback and popup state; native owns
  PKCE and provider configuration. Browser input cannot select native identities,
  destinations or grants.

The catalog accepts up to 200 unique gateway/server mappings. Authorization-code
popup flows use single-valued parameters; repeated `resource` parameters are unsupported.

`POST /api/me/mcp/{id}/connect` accepts only `{}` and the approved `Origin` header.
It prepares the verified Keycloak email's native account and starts native OAuth
as that user, returning only `authorization_url` and `callback_origin`. Reconnect
is manual. `GET /api/me/mcp/{id}/status` rechecks existing roles/membership read-only,
never repairing revoked access. Both need `studio-user`, `llm:invoke` and matching
`mcp:<id>:invoke`. Caller credentials/identity headers are not forwarded, and the
provisioning service never identifies user OAuth. Traces retain Keycloak subject/
bridge principal attribution; email changes/conflicts remain operator-managed.

Status is metadata: `valid`/`near_expiry` → `connected`, `missing` → `connect required`,
`expired` → `refresh pending`, unknown/failure → unavailable. Expiry does not prove
reconnection is needed or refresh is possible. Revocation may appear only on a call;
native `invalid_grant` removes the record, while transient refresh failures preserve it.

### Base/operator runtime contract

Pinned ContextForge v1.0.11 source is
`077071bbb43599dd5ab9372ebdbb9a8e686a9816`:

1. `OAUTH_TOKEN_BACKEND=database` isolates tokens by `(gateway_id, app_user_email)`.
   Temporary PostgreSQL storage bypasses, but does not fix, the Vault team-scope
   defect (Base #424). Supply persistent strong `AUTH_ENCRYPTION_SECRET` from
   OpenBao/ESO. Native encryption has plaintext fallbacks: the operator must check
   actual ciphertext and restart/decryption in the adopted image, not trust Studio.
2. Native `MCP_CLIENT_AUTH_ENABLED=false`, `TRUST_PROXY_AUTH=true`,
   `TRUST_PROXY_AUTH_DANGEROUSLY=true`,
   `PROXY_USER_HEADER=x-contextforge-account-email`, `MCP_REQUIRE_AUTH=true`,
   `REQUIRE_USER_IN_DB=true`, `MCPGATEWAY_DIRECT_PROXY_ENABLED=false` require private
   trusted Gateway/Studio API ingress. Proxy RBAC requires an identity header and
   **does not validate bearer credentials**, including on administrative APIs.
   Studio uses its configured service email for provisioning/account checks and
   the verified human email for OAuth/status. The service must be active, verified,
   non-admin and distinct
   from native `PLATFORM_ADMIN_EMAIL`. Its active, non-expiring, non-inheriting
   global/fixed-team role assignments must collectively contain exactly
   `admin.user_management`, `teams.read`, `teams.manage_members`; its membership
   in the configured non-personal team must be active `owner`. Avoid broad native
   `team_admin` defaults on this account. Studio checks service state/grants/ownership
   read-only before user preparation/status. Restrict native ingress to trusted
   workloads; Gateway routes must expose only approved invocation paths, never
   administrative APIs. A service header is not an independent credential: workload
   trust is the boundary. No signing key, broker or upstream patch is added.
3. **Accepted public-visibility limitation:** proxy OAuth lacks `token_teams` and
   denies native team/private registrations. Gateway/server must use native `public`
   visibility and fixed-team ownership. Ownership/private ingress do **not** restore
   native team isolation: public resources can cross teams. Scope is one internal
   team, private approved routes, platform grants and per-email credentials.
4. Keep one service-owned non-personal team, active non-admin verified-email users,
   an empty global role and exactly `tools.read`, `tools.execute`, `servers.read`,
   `servers.use`, `gateways.read` on the team role, with no inheritance. Set native
   default role **names**, disable personal-team creation and keep native login,
   reset, admin, discovery and credential-management endpoints private. Registration
   ownership, approved tool/server membership and OAuth-only provider headers remain
   operator-controlled; invocation must not gain caller Authorization via plugins.
5. Route **exact GET `/oauth/callback`** on the Studio HTTPS Gateway directly to
   Studio API's existing application Service/port, without prefix rewrite or JWT
   admission. Studio's exact callback auth exclusion rejects non-GET methods with
   405 before routing; every other operational path remains JWT-protected.
   Keep native `/oauth/callback` and legacy pages private. Studio rejects
   non-`popup.` states, duplicate/unknown or oversized parameters before forwarding
   only code/state unchanged to its fixed private `CONTEXTFORGE_URL` callback, over
   verified TLS using `CONTEXTFORGE_CA_CERT` when needed. No caller headers, cookies,
   service identity or bearer are sent; provider denials get a local generic error.
   Optional `iss` accepts an HTTPS URL up to 2,048 characters, without credentials,
   query, fragment, whitespace or backslashes. It is ignored after syntax validation;
   Studio does not bind it to state or use it for routing, forwarding or logging.
   Native retains state validation, PKCE, code exchange and token storage. Only the
   pinned native success-popup shape is accepted; Studio renders fresh status-only
   HTML, never native bodies, cookies, redirects, JWTs or error details. Responses
   use no-store, no-referrer, nosniff and a nonce-based CSP. Popup origin is now Studio.
   **Accepted transferable-URL risk:** callback forwarding does not authenticate
   the completing browser/account. Someone authorizing a copied URL stores their
   provider connection under the initiator's account. PKCE and popup origin/source
   checks do not prevent this. Popup messages only trigger authenticated status reads.
   Studio disables application Uvicorn access logs and HTTPX/httpcore wire diagnostics
   to avoid callback code/state/header logging; dev Uvicorn uses `--no-access-log` too.
   Base must suppress callback query/body/header logs at Gateway and native, including
   native OAuth/DB exception logging. Studio cannot protect those external logs.

For the GitHub sample, operators preregister one approved GitHub App or OAuth App
for `https://api.githubcopilot.com/mcp`, with GitHub login OAuth endpoints and the
approved callback. Its client secret comes from OpenBao; native registration copies
live in PostgreSQL. Compatible Studio/bridge/extProc images, Base wiring and live
two-user/PII/refresh/restart checks belong to operator adoption. Source validation
does not claim deployment, actual ciphertext or live OAuth verification.

## Requirements

Local development needs Docker Compose (default Docker context), Python 3, and
OpenSSL on the host. Application runtimes run in containers. The API does not
start unless Keycloak authentication initializes successfully.

## Local Development

Start the isolated development stack:

```bash
./start_dev.sh
```

The web application listens on **http://localhost:3001**, the API on
`http://localhost:4010`, and Keycloak on **http://localhost:4081**. Use
`localhost` for login, matching the registered redirect and issuer. The first
start creates ignored `.dev-local/credentials.env` and locally signed workload
certificates under `.dev-local/tls/`. The launcher displays the
`DEV_USER_PASSWORD` from that env file after setup; it is the initial password
for `developer`, `viewer`, and `no-access`. `developer`
has all Studio feature roles and delegated Keycloak read access; `viewer` has
only Studio admission; `no-access` has no Studio access. Existing passwords and
API keys are retained on subsequent starts.

The launcher waits for PostgreSQL, Keycloak, and the application, rerunning
idempotent Keycloak configuration and Studio notice database migrations on each
launch. `Ctrl+C` stops containers without deleting their volumes. Other commands:

```bash
./start_dev.sh up --detach
./start_dev.sh logs
./start_dev.sh ps
./start_dev.sh setup  # recheck realm and account setup
./start_dev.sh stop
./start_dev.sh down   # retains database and API-key volumes
```

Keycloak and the API-key bridge are real services. The bridge persists keys in
its own SQLite volume. Studio notice preferences persist in a separate `studio`
database in the local PostgreSQL container. Four separate dev-only services built
from `dev/simulators/` provide synthetic responses for PII Engine, AgentGateway
analytics, OpenSearch, and Langfuse. The browser always talks through Studio's
ordinary authenticated API. The PII sample recognizes **only** the literal demo
addresses
`john@example.com` and `a@example.com` with `pass`, `mask`, or `block`; other
actions return an explicit unsupported-sample result. It is not a policy
validator or a real PII detector. Usage and logs are synthetic, including
current example dates; they are not observations from a gateway or Kubernetes
cluster. The PII connection still requires a
locally signed Studio client certificate; OpenSearch uses verified local TLS
and a generated basic-auth password. No cluster credentials are accessed.

The **LLM & MCP logs** page is enabled locally. Its fictional chat messages
follow the Langfuse v4 generation input/output array shape observed in the
development cluster, including sample reversible-replacement placeholders and a
synthetic PII Engine notice in a title-generation request. The local Brave MCP
call has a recorded query and result; a second call shows
how missing parameters and session IDs appear in the UI. Example LLM exchanges
share a demo session ID so related rows have the same color. Synthetic observation
metadata includes requested and routed models plus HTTP method, path, and status.
They contain no copied prompts, user identifiers, or credentials from Langfuse;
request headers were not present in the sampled generation input/output records.
The simulated project keys work only with the local Langfuse simulator.

Optional automated local smoke check (requires host `uv` and Python 3.12):

```bash
uv run --project apps/api python dev/smoke.py
uv run --project apps/api python dev/smoke.py --keys  # also creates and revokes a demo API key
```

The smoke check exercises browser-style PKCE login, Studio roles, the real
bridge, and sample integrations without printing passwords or tokens. It does
not replace visual browser testing.

For direct host-based work on the web or API, install Node.js 22, pnpm 9.15.4,
Python 3.12, and [uv](https://docs.astral.sh/uv/). `.env.example` describes the
separate manual integration settings. `pnpm --filter web dev` alone runs the UI
on port 3000, with its default proxy to `localhost:4010`.

OpenSearch verifies TLS with the system trust store by default, or with the CA
file configured by `K8S_STUDIO_OPENSEARCH_CA_CERT`. The API rejects an insecure
development option for non-loopback hosts.

PII Engine also verifies its server certificate by default while always using
the configured workload client certificate. Local development may explicitly
set `K8S_STUDIO_PII_ENGINE_ALLOW_INSECURE_LOCAL=true` only for `localhost`,
`127.0.0.1`, or `::1`; lookalike and remote hostnames are rejected.

Usage views call the private AgentGateway admin API configured by
`K8S_STUDIO_AGENTGATEWAY_ADMIN_URL`. The API client ignores ambient proxy
settings and accepts only an absolute HTTP(S) URL without embedded credentials,
a query, or a fragment. `K8S_STUDIO_USAGE_TIMEZONE` controls calendar boundaries
and defaults to `Europe/Berlin`, including daylight-saving transitions.
Langfuse tracing is separate from this usage integration.

Historical usage remains visible when a Keycloak profile is unavailable, labeled
`Unknown – ID <user-id>` instead of a name. Missing profiles are expected lookup
results, not dashboard failures. For callers allowed to read a profile,
`/users/<user-id>` shows `User not found` on a 404 and does not display API-key
management for that missing user. Profile and API-key authorization remain separate.

The optional **LLM & MCP logs** page reads the signed-in person's ten most recent
matching Langfuse v4 LLM generations and MCP tool calls. The All, LLM, and MCP
filter changes which observations are returned. The table shows recorded token
totals and USD cost where available, with the response preview last. It shows
the concrete model (preferring the response model on reroutes) and groups MCP
server and tool together. Expanded entries group Sent and Received
or Parameters and Result, with a Recorded payload toggle and recorded request time.
The Langfuse observation contains model-visible content rather than the original
HTTP wire request. A separate metadata card shows an allowlisted subset of the
observation's context as readable key/value rows or JSON; arbitrary URLs and
paths are excluded and credential-like values are masked before reaching the browser.
The current tracing pipeline records HTTP context but not request headers.
Session IDs come from the observation or its Langfuse metadata and color-code
related rows; unattributed tool calls may lack a session ID. MCP traces may put
parameters and results in observation metadata instead of the ordinary
input/output fields; unavailable fields are shown as missing. Query searches
model input/output and recorded MCP query metadata; optional From/To local
timestamps limit searches to at most 90 days. Data not
recorded by tracing is shown as missing, and the page does not change PII or
tracing policy. Admins cannot view another person's trace content through
Studio. Unattributed tool calls are not included in a person's timeline.
Unlike the separate usage totals, there is no other-user route.

`K8S_STUDIO_LLM_LOGS_ENABLED=false` by default. When disabled the API route
returns 404 and the API process does not start a Langfuse client. Base additionally
omits the API Pod's project credentials and Langfuse egress unless explicitly
enabled. When enabled, set `K8S_STUDIO_LANGFUSE_URL` and the project-scoped
`K8S_STUDIO_LANGFUSE_PUBLIC_KEY` and `K8S_STUDIO_LANGFUSE_SECRET_KEY` on the API
process only. Keep these keys out of the browser. Query text is sent in the
Studio request body rather than in its URL; responses include `Cache-Control:
no-store`. Langfuse project keys can access every trace in the project, so the
server always enforces the verified Keycloak subject for both input and output
searches and rejects misattributed upstream results.

The default landing page is the authenticated user's own info page. Explicit
local deep links are preserved through login; self-service does not require a
specialized administrator role beyond Studio admission.

Personal Notice display (`/notices`) and API Keys (`/api-keys`) live under
Configuration instead of the profile. Creating a personal API key can save
notice overrides alongside its permissions; existing keys have a Notice settings
action. PII Policy remains visible only to users with the `pii-admin` role.

The user info page displays a Recharts 3.10.0 daily stacked chart by requested
model, with an instant Tokens/USD switch, model visibility controls, and
selected-range totals. It defaults to 30 calendar days including today and
refreshes every 30 seconds. Costs are reported sums and may omit unpriced
requests. Today is partial; unknown models and empty days are retained.

The **Usage** sidebar page (`/usage`) has date presets and an inclusive custom
range (up to 90 days), headline totals, a per-model table, daily trends, and a
daily table. It defaults to this month in the API's configured calendar timezone.
Everyone can view their own usage. Users with `langfuse-admin` also see an
**All users** option (selected by default), an active-user selector, and a
descending, metric-selectable per-person breakdown. Admin-only
`GET /api/usage/daily` and `GET /api/usage/people` query AgentGateway without a
user filter; the latter groups by the verified `agentgateway.user` attribute
and returns only opaque IDs and totals, never raw logs or upstream filter
options. Users with both `langfuse-admin` and `keycloak-admin` see names for
the first 20 active people and their selected user through delegated Keycloak
reads; others see shortened IDs with full IDs on hover. The user picker lists
active principals in the selected period plus the viewer's own account.

`GET /api/users/{user_id}/usage/daily` accepts optional inclusive `start` and
`end` dates (`YYYY-MM-DD`), with a maximum of 90 days and no future end date.
Without `end`, it ends today; without `start`, it starts 29 days before the end.
It returns `timezone`, `start_date`, `end_date`, `today`, and `days`, each with a
`date` and `models` containing nullable `model`, `requests`, `total_tokens`, and
`cost_usd`. Self and `langfuse-admin` authorization matches the retained
`/usage` period-totals endpoint. Invalid ranges return 422; unavailable or
invalid gateway summaries return 502 without exposing upstream content.

## Validation

Run the JavaScript and TypeScript checks from the repository root:

```bash
pnpm lint
pnpm typecheck
pnpm build
```

Run API checks from `apps/api`:

```bash
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
```

Automated tests focus on API behavior and security boundaries. The web app has
no browser-simulation test suite; lint, type checks and builds remain required.
Check user-facing flows visually when changing the UI.

## Containers

The API image uses `apps/api` as its build context. The web image uses the
repository root so pnpm workspace files are available:

```bash
docker build -t studio-api:local apps/api
docker build -t studio-web:local -f apps/web/Dockerfile .
```

Runtime secrets must be supplied by the deployment environment and must not be
built into either image.

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting. Do not include
credentials, tokens, certificates, personal data, or production configuration
in public reports.

## License

Licensed under the [MIT License](LICENSE).
