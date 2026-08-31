# AI Stack Studio

AI Stack Studio is a web dashboard and authenticated API for operating AI
platform services. It provides policy inspection and testing, log search, user
and OIDC-client administration, API-key management, and per-user usage views.

The repository is a pnpm/Turbo monorepo containing:

- `apps/web`: Next.js 16 and React 19 frontend.
- `apps/api`: FastAPI backend managed with uv.

## Architecture

The browser loads deployment-specific OIDC settings from `/env.js`. The web app
proxies `/api/*` to the FastAPI service, which validates Keycloak JWTs and
enforces feature-specific realm roles. The API communicates with PII Engine
over workload mTLS and uses authenticated integrations for OpenSearch,
Keycloak administration, the API-key bridge, and Langfuse.

Default service URLs in the API settings are intentional Kubernetes service DNS
names. Deployments override identity, credentials, certificates, and any
environment-specific endpoints through `K8S_STUDIO_*` environment variables.

## Requirements

- Node.js 22 or later
- pnpm 9.15.4
- Python 3.12
- [uv](https://docs.astral.sh/uv/)

The full application also requires reachable OIDC and backend integrations.
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
