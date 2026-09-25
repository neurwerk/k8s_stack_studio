# k8s_stack_studio

AI Stack Studio — a Supabase-style dashboard for managing AI infrastructure.
Monorepo with a FastAPI backend (Python) and a Next.js 16 frontend (TypeScript).

## What it does

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health`, `GET /metrics` | none, management port only | Readiness probe and Prometheus metrics |
| `GET /api/version` | none | Public service version |
| Every other `/api/*` route | `studio-user` | Application admission after Keycloak JWT verification |
| `POST /api/policy-engine/analyze` | `studio-user`, `pii-admin` | Proxy to PII Engine `/v1/studio/analyze-request` over dedicated mTLS |
| `POST /api/policy-engine/evaluate` | `studio-user`, `pii-admin` | Strict proxy to model-free PII Engine `/v1/studio/evaluate-policy` over dedicated mTLS |
| `GET /api/policy-engine/actions`, `GET /api/policy-engine/policy` | `studio-user`, `pii-admin` | Shared PII Engine metadata |
| `GET /api/logs` | `studio-user`, `opensearch-admin` | Search pod logs via OpenSearch (newest 100 by default; text, Kubernetes, classification, time, size, offset, and index filters) |
| `GET /api/admin/users`, `GET /api/admin/clients` | `studio-user`, `keycloak-admin` | Keycloak administration |
| `GET /api/admin/groups`, `GET /api/admin/roles` | `studio-user`, `keycloak-admin` | Read-only Keycloak groups and realm roles |
| Admin user, group, and client access routes | `studio-user`, `keycloak-admin` | Read-only memberships, role mappings, client roles, and service-account access |
| `GET /api/admin/recent-signins` | `studio-user`, `keycloak-admin` | Read-only seven-day successful LOGIN summary for up to 25 user IDs |
| `GET /api/users/{user_id}/usage` | `studio-user`, self or `langfuse-admin` | Calls, total tokens, and USD cost from AgentGateway private analytics |
| `GET /api/users/{user_id}/usage/daily` | `studio-user`, self or `langfuse-admin` | Daily requested-model tokens, calls, and reported USD; inclusive date range up to 90 days |
| `GET /api/usage/daily`, `GET /api/usage/people` | `studio-user`, `langfuse-admin` | All-user daily model totals and active-person breakdown; inclusive date range up to 90 days |
| `GET /api/users/{user_id}/agentgateway-permissions` | `studio-user`, self or `api-key-admin` | Transparent bridge `GET /permissions?user_id=...` proxy |
| API-key list/create/revoke routes | `studio-user`, self or `api-key-admin` | Bridge proxy; creates require immutable `name`, non-empty `permissions`, and `expires_in_days` from 1 to 365; no renewal route |

The logs endpoint accepts paired timezone-aware `start` and `end` bounds, with
`start < end`; invalid or incomplete ranges return 422. Bounds are normalized
to UTC and applied inclusively to `@timestamp`, alongside existing filters.
Omitting both retains the newest-first unbounded-time search.
`/logs` accepts `namespace`, `pod`, `q`, `level`, `failure_type`, `start`, and
`end`, plus a UI-only positive `page`; its UI-only `at` Unix-seconds shortcut selects exactly ten minutes before through five minutes
after the event. Valid explicit bounds take precedence. Invalid time links
show an error without searching. From/To controls use local time; manual searches
write explicit UTC bounds to the URL, remove `at`, and reset to page 1. Previous
and Next retain the active URL filters and paginate within OpenSearch's 10,000-result
window. Log level is normalized
collector metadata; failure type is present only for records accepted by the
application-error classifier. Older records display as UNKNOWN and Unclassified.

The logs endpoint queries OpenSearch with the dedicated read-only
`studio-logs-read` internal user (basic auth, password patched into
`frontend-studio-api-secret` by the monitor-opensearch init Job). TLS is
verified against the internal CA mounted at `K8S_STUDIO_OPENSEARCH_CA_CERT`
(empty = use the system trust store). An explicit insecure option is accepted
only for loopback local-development endpoints.

Settings are via `K8S_STUDIO_*` env vars.
Usage analytics calls AgentGateway's private admin API through a dedicated,
lifespan-managed client that ignores ambient proxy settings. The browser never
calls AgentGateway directly, and the existing `langfuse-admin` role remains the
cross-user usage authorization contract.
`K8S_STUDIO_USAGE_TIMEZONE` defaults to `Europe/Berlin`; daily analytics honor
local calendar days and daylight-saving transitions. The user info page uses
Recharts 3.10.0 with a Tokens/USD toggle and defaults to the last 30 days.
PII Engine server verification can be disabled only through the explicit local
option and only for exact `localhost`, `127.0.0.1`, or `::1` endpoints; workload
client certificates remain required.

The Next.js frontend consumes the API and renders a dashboard with:

- **Sidebar** — collapsible dark sidebar with icon navigation
- **PII Policy** (`/policy-engine`, `pii-admin` role) — config panel, YAML preview, strict policy validation, detailed PII diagnostics, and deterministic model-free simulation
- **Logs** (`/logs`, `opensearch-admin` role) — OpenSearch log viewer with text, namespace, pod, level, failure-type, and time filters
- **Usage** (`/usage`) — model and daily usage dashboard; `langfuse-admin` can select all active users or one user, with a per-person chart
- **Users / Groups / Realm Roles / Clients** (`keycloak-admin` role) — read-only Keycloak access views and existing user controls
- **API Keys** — per-user API key management
- **Error / loading states** — spinner while loading, error card when the API is unreachable

The Users list uses `first` (nonnegative offset) and `max` (1-25, default 25)
on `/api/admin/users`, retaining its array response. Search is debounced and
requests are cancelled when search/page changes. Status separates account
Enabled/Disabled/unknown from email verified/unverified/unknown or no email.
Self-profile account state is unknown because an issued JWT is not evidence of
the account's current enabled state.

`/api/admin/recent-signins` accepts repeated `user_ids` query parameters and
returns UTC `window_start`, `window_end`, and a `users` map. Each value has
`status` (`recorded`, `no_record`, or `unavailable`) and nullable ISO timestamp.
The rolling window is exactly seven days. Queries forward the administrator's
own bearer token, require Keycloak `realm-management/view-events`, and filter
by user, successful `LOGIN`, descending time, max 1, and epoch-millisecond date
bounds, without a client filter. There are at most four concurrent event
requests per batch, each with a five-second HTTP timeout. Only normalized
timestamps reach the browser, not raw events or their details. Activity errors
do not hide users. No record is not proof that a user never signed in; retention
and event collection may limit history. Keycloak role provisioning is owned by
the platform, not Studio.

## Project structure

```
apps/
├── api/                         ← FastAPI backend (Python, uv-managed)
│   ├── pyproject.toml           ← hatchling build, ruff, ty, pytest-asyncio
│   ├── Dockerfile               ← python:3.12-slim, appuser, EXPOSE 4010
│   ├── src/k8s_stack_studio/
│   │   ├── config/
│   │   │   └── settings.py      ← Pydantic BaseSettings (K8S_STUDIO_ prefix)
│   │   ├── lib/
│   │   │   ├── http_client.py   ← Shared httpx.AsyncClient (lifespan-managed)
│   │   │   ├── agentgateway.py  ← Private request-log analytics client
│   │   │   ├── pii_engine.py    ← PiiEngineClient — typed mTLS engine client
│   │   │   ├── auth.py          ← Keycloak OIDC + studio-user admission middleware
│   │   │   ├── dependencies.py  ← FastAPI Depends() wiring
│   │   │   ├── keycloak_admin.py
│   │   │   └── opensearch.py
│   │   ├── controllers/
│   │   │   ├── policy_engine.py ← analyze, evaluate, actions, and policy routes
│   │   │   ├── admin.py         ← Keycloak admin routes
│   │   │   ├── api_keys.py      ← API keys and bridge permission proxy
│   │   │   └── logs.py          ← OpenSearch log viewer
│   │   ├── models/
│   │   │   └── policy_engine.py ← Strict Pydantic v2 Studio contract
│   │   └── main.py              ← FastAPI app factory + uvicorn entry point
│   └── tests/
│       ├── test_logs.py         ← OpenSearch query + role tests
│       └── test_policy_engine.py ← strict PII Engine contracts and proxy tests
│
└── web/                         ← Next.js 16 + Tailwind v4 + shadcn/ui
    ├── app/
    │   ├── layout.tsx           ← Root layout (dark sidebar, Geist font)
    │   ├── page.tsx             ← Landing → authenticated user's own info page
    │   ├── policy-engine/       ← Policy Engineer page
    │   ├── logs/                ← Log viewer page
    │   ├── users/               ← User management pages
    │   ├── clients/             ← Client management page
    │   ├── auth/                ← OIDC callback
    │   └── globals.css          ← Zinc/Neutral CSS variables (light + dark)
    ├── components/
    │   ├── sidebar.tsx          ← Collapsible sidebar (lucide-react icons)
    │   ├── config-panel.tsx     ← LLM policy config editor (safety/PII/classifier/routing)
    │   ├── config-preview.tsx   ← Generated YAML preview
    │   ├── policy-tester.tsx    ← original findings, overlap decisions, transformed request, and simulation viewer
    │   ├── api-key-manager.tsx  ← API key management
    │   ├── auth-guard.tsx       ← Auth HOC
    │   ├── oidc-provider.tsx    ← OIDC provider wrapper
    │   └── user-table.tsx       ← User table
    └── lib/
        ├── api/
        │   ├── client.ts        ← Typed fetch wrapper with OIDC auth
        │   ├── policy-engine.ts ← typed analyze/evaluate/metadata clients
        │   ├── admin.ts         ← Keycloak admin calls
        │   └── logs.ts          ← Log queries
        ├── auth/roles.ts        ← Role helpers
        ├── config-generator.ts  ← ConfigState → YAML generation
        └── oidc/settings.ts     ← OIDC settings

turbo.json                        ← Unified `pnpm dev` (both apps)
pnpm-workspace.yaml               ← apps/*
```

## Architecture

1. Next.js proxies `/api/*` → `localhost:4010` by default, or `STUDIO_API_URL` in Compose (`next.config.ts`)
2. FastAPI admits operational routes only after Keycloak verifies a JWT with the `studio-user` realm role; feature routes retain their focused leaf-role checks
3. The policy-engine endpoints proxy directly to PII Engine v1 over workload mTLS; human JWTs are not forwarded
4. Policy evaluation is deterministic and model-free; Studio displays the Engine's transformed request, simulated model-facing echo, restored user response, and bounded diagnostics
5. Usage queries are authorized by Studio and proxied to AgentGateway's private request-log analytics API; unrelated OTLP/Langfuse tracing behavior is unchanged
6. Verified `resource_access.agentgateway.roles` remains in the session contract for API-key entitlement management, but the policy tester never calls AgentGateway
7. Sidebar uses `lucide-react` icons and is collapsible (width toggles between 16rem and 4rem)

## Frontend details

- **Styling**: Tailwind v4 with `tw-animate-css` for shadcn/ui animations.  Dark mode
  by default (`<html class="dark">`).  Color tokens defined as CSS variables in
  `globals.css` following shadcn/ui's Zinc palette (light) and Zinc-900 (dark).
- **Fonts**: Geist Sans (body) + Geist Mono (monospace for code/IDs).
- **Components**: Built inline (no `shadcn` CLI used) to keep the dependency
  surface minimal.  Uses CSS variable tokens directly.
- **API layer**: `lib/api/client.ts` exports `apiPost`/`apiGet` with OIDC auth
  header injection.

## Local development

```bash
# Start isolated containers with local Keycloak, bridge, and sample integrations
./start_dev.sh
# → Next.js on http://localhost:3001
# → FastAPI on http://localhost:4010
# → Keycloak on http://localhost:4081

# For host-side validation, install JS and Python dependencies first:
pnpm install --frozen-lockfile
uv sync --project apps/api --dev

# Python linting & tests (from apps/api/)
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest -v
```

All four checks (ruff check, ruff format, ty, pytest) should pass before committing.

## Building and pushing

### Images

CI publishes two images:
- `ghcr.io/neurwerk/k8s-stack-studio-api` (FastAPI backend)
- `ghcr.io/neurwerk/k8s-stack-studio-web` (Next.js frontend)

### Releasing

1. Open a release issue and make the aligned API, web, and lockfile version
   changes on a dedicated branch.
2. Run the complete API and web quality gates, then open a pull request that
   links the release issue and records the results.
3. After required CI and review complete, obtain explicit authorization and
   squash-merge the pull request.
4. After separate release authorization, update local `main`, create the exact
   tag from the merged commit, and push only that tag:
   ```bash
   git switch main
   git pull --ff-only origin main
   git tag v0.x.x
   git push origin v0.x.x
   ```
5. GitHub Actions builds and pushes versioned `linux/amd64` images to GHCR.

Do not push release preparation directly to `main`, combine the branch push
with the tag push, or treat merge authorization as release authorization.

Only `v*` tags publish images. Branch pushes do not publish images.

### Local build

```bash
# API
docker build -t studio-api:local apps/api

# Web
docker build -t studio-web:local -f apps/web/Dockerfile .
```

## Repository

`https://github.com/neurwerk/k8s_stack_studio`
