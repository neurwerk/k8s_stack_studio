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
| `GET /api/logs` | `studio-user`, `opensearch-admin` | Search pod logs via OpenSearch (newest 100 by default; `q`/`namespace`/`pod`/`size`/`index` filters) |
| `GET /api/admin/users`, `GET /api/admin/clients` | `studio-user`, `keycloak-admin` | Keycloak administration |
| `GET /api/users/{user_id}/agentgateway-permissions` | `studio-user`, self or `api-key-admin` | Transparent bridge `GET /permissions?user_id=...` proxy |
| API-key list/create/revoke routes | `studio-user`, self or `api-key-admin` | Bridge proxy; creates require immutable `name`, non-empty `permissions`, and `expires_in_days` from 1 to 365; no renewal route |

The logs endpoint queries OpenSearch with the dedicated read-only
`studio-logs-read` internal user (basic auth, password patched into
`frontend-studio-api-secret` by the monitor-opensearch init Job). TLS is
verified against the internal CA mounted at `K8S_STUDIO_OPENSEARCH_CA_CERT`
(empty = use the system trust store). An explicit insecure option is accepted
only for loopback local-development endpoints.

Settings are via `K8S_STUDIO_*` env vars.
PII Engine server verification can be disabled only through the explicit local
option and only for exact `localhost`, `127.0.0.1`, or `::1` endpoints; workload
client certificates remain required.

The Next.js frontend consumes the API and renders a dashboard with:

- **Sidebar** — collapsible dark sidebar with icon navigation
- **PII Policy** (`/policy-engine`, `pii-admin` role) — config panel, YAML preview, strict policy validation, detailed PII diagnostics, and deterministic model-free simulation
- **Logs** (`/logs`, `opensearch-admin` role) — OpenSearch log viewer with filter bar (query, namespace, pod)
- **Users / Clients** (`/users`, `/clients`, `keycloak-admin` role) — Keycloak user and client management
- **API Keys** — per-user API key management
- **Error / loading states** — spinner while loading, error card when the API is unreachable

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
    │   ├── page.tsx             ← Landing → /policy-engine
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

1. Next.js proxies `/api/*` → `localhost:4010` (configured in `next.config.ts`)
2. FastAPI admits operational routes only after Keycloak verifies a JWT with the `studio-user` realm role; feature routes retain their focused leaf-role checks
3. The policy-engine endpoints proxy directly to PII Engine v1 over workload mTLS; human JWTs are not forwarded
4. Policy evaluation is deterministic and model-free; Studio displays the Engine's transformed request, simulated model-facing echo, restored user response, and bounded diagnostics
5. Verified `resource_access.agentgateway.roles` remains in the session contract for API-key entitlement management, but the policy tester never calls AgentGateway
6. Sidebar uses `lucide-react` icons and is collapsible (width toggles between 16rem and 4rem)

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
# Install JS dependencies
pnpm install

# Install Python dependencies
cd apps/api && uv sync --dev && cd ../..

# Configure explicit local endpoints and certificate paths
cp .env.example .env.local

# Run both apps
./start_dev.sh
# → Next.js on http://localhost:3000
# → FastAPI on http://localhost:4010

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
