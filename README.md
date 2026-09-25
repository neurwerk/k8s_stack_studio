# AI Stack Studio

AI Stack Studio is a web dashboard and authenticated API for operating AI
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

Studio mirrors PII Engine's typed Chat Completions `stream_options` contract:
omitted or null options are accepted; a non-null object requires `stream: true`
and a strict boolean `include_usage` field. Unknown option fields are rejected.
Analysis and evaluation responses preserve these options, including explicit null.

Default service URLs in the API settings are intentional Kubernetes service DNS
names. Deployments override identity, credentials, certificates, and any
environment-specific endpoints through `K8S_STUDIO_*` environment variables.

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
certificates under `.dev-local/tls/`; the `DEV_USER_PASSWORD` in that env file
is the initial password for `developer`, `viewer`, and `no-access`. `developer`
has all Studio feature roles and delegated Keycloak read access; `viewer` has
only Studio admission; `no-access` has no Studio access. Existing passwords and
API keys are retained on subsequent starts.

The launcher waits for PostgreSQL, Keycloak, and the application, rerunning
idempotent Keycloak configuration on each launch. `Ctrl+C` stops containers
without deleting their volumes. Other commands:

```bash
./start_dev.sh up --detach
./start_dev.sh logs
./start_dev.sh ps
./start_dev.sh setup  # recheck realm and account setup
./start_dev.sh stop
./start_dev.sh down   # retains database and API-key volumes
```

Keycloak and the API-key bridge are real services. The bridge persists keys in
its own SQLite volume. Three separate dev-only services built from
`dev/simulators/` provide synthetic responses for PII Engine, AgentGateway
analytics, and OpenSearch. The browser always talks through Studio's ordinary
authenticated API. The PII sample recognizes **only** the literal demo addresses
`john@example.com` and `a@example.com` with `pass`, `mask`, or `block`; other
actions return an explicit unsupported-sample result. It is not a policy
validator or a real PII detector. Usage and logs are synthetic, including
current example dates; they are not observations from a gateway or Kubernetes
cluster. The PII connection still requires a
locally signed Studio client certificate; OpenSearch uses verified local TLS
and a generated basic-auth password. No cluster credentials are accessed.

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

The default landing page is the authenticated user's own info page. Explicit
local deep links are preserved through login; self-service does not require a
specialized administrator role beyond Studio admission.

The user info page displays a Recharts 3.10.0 daily stacked chart by requested
model, with an instant Tokens/USD switch, model visibility controls, and
selected-range totals. It defaults to 30 calendar days including today and
refreshes every 30 seconds. Costs are reported sums and may omit unpriced
requests. Today is partial; unknown models and empty days are retained.

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
pnpm test
pnpm build
```

Run API checks from `apps/api`:

```bash
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
```

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
