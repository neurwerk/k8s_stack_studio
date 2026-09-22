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

- Node.js 22 or later
- pnpm 9.15.4
- Python 3.12
- [uv](https://docs.astral.sh/uv/)

The full application requires reachable OIDC and backend integrations. The API
does not start unless its Keycloak authentication initialization succeeds, so
Kubernetes retries it instead of exposing endpoints without initialized clients.
Studio does not retrieve credentials or certificates from a cluster. Provide
local certificate paths and credentials through your own ignored env file.

## Local Development

Install dependencies:

```bash
pnpm install
uv sync --project apps/api --dev
```

Create `.env.local` from `.env.example`, replace the reserved example values,
and provide paths to local PII Engine client certificates. Then start both
applications:

```bash
./start_dev.sh
```

The web application listens on `http://localhost:3000` and the API on
`http://localhost:4010`. To work on the UI without starting the API, run:

```bash
pnpm --filter web dev
```

OpenSearch verifies TLS with the system trust store by default, or with the CA
file configured by `K8S_STUDIO_OPENSEARCH_CA_CERT`. A self-signed loopback-only
development endpoint may set `K8S_STUDIO_OPENSEARCH_ALLOW_INSECURE_LOCAL=true`.
The API rejects that option for non-loopback hosts.

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
