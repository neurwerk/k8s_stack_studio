# Development

## Local stack

Run from the repository root with Bash, Python 3, OpenSSL, and Docker Compose available in Docker's `default` context:

```bash
./start_dev.sh up --detach
./start_dev.sh ps
./start_dev.sh logs
```

[The launcher](../../start_dev.sh) creates ignored `.dev-local/` credentials and TLS files, builds the development containers, configures local Keycloak, creates the Studio database, and runs its migrations. Open Studio at `http://localhost:3001`; local Keycloak is at `http://localhost:4081`. The launcher displays the generated password for `developer`, `viewer`, and `no-access`.

[Compose](../../docker-compose.dev.yaml) runs real Keycloak, PostgreSQL, and the API Key Bridge alongside PII, usage, log, and Langfuse simulators. The API uses [MCP preview routes](../../dev/mcp_preview.py); this environment exercises the interface rather than production MCP publication. API source reloads in its container and the web app runs the Next.js development server.

`./start_dev.sh stop` stops the environment. `./start_dev.sh down` removes its containers and networks while retaining named volumes. Keep `.dev-local/` with those volumes because it holds their matching local credentials. Worktrees get their own Compose project name, but host ports remain fixed, so run only one local stack on those ports at a time.

## Quality checks

The [quality workflow](../../.github/workflows/quality.yml) defines the required checks; there is no Makefile. API checks use Python 3.12 and `uv`. From `apps/api/`:

```bash
uv lock --check
uv sync --locked --dev
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen ty check
uv run --frozen pytest
```

Database-backed tests require a disposable PostgreSQL database and `MCP_SETUP_TEST_DATABASE_URL`; use the workflow's test service configuration. This must not point at an application database.

Web checks use Node.js 22 and the pnpm version declared in [package.json](../../package.json). From the repository root:

```bash
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm --filter web test:mcp
pnpm --filter web test:gateway
pnpm build
```

These are the existing lint, type, regression, and build commands. Local integration startup is separate from these checks; bare `pnpm dev` does not provision Keycloak, workload certificates, or the database. See [contribution guidance](../../.github/CONTRIBUTING.md) for the review workflow.
