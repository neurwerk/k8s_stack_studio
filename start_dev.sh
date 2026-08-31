#!/usr/bin/env bash
# Start the local Studio web and API processes from explicit local settings.
# This script never connects to Kubernetes or retrieves secrets.

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${STUDIO_ENV_FILE:-.env.local}"

if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$ROOT_DIR/$ENV_FILE"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Local environment file not found: %s\n' "$ENV_FILE" >&2
  printf 'Create it from .env.example and replace the reserved example values.\n' >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

required=(
  OIDC_AUTHORITY
  OIDC_CLIENT_ID
  K8S_STUDIO_PII_ENGINE_URL
  K8S_STUDIO_PII_ENGINE_CLIENT_CERT
  K8S_STUDIO_PII_ENGINE_CLIENT_KEY
)

if [[ "${K8S_STUDIO_ALLOW_UNAUTHENTICATED_LOCAL:-false}" != "true" ]]; then
  required+=(
    K8S_STUDIO_KEYCLOAK_SERVER_URL
    K8S_STUDIO_KEYCLOAK_REALM
    K8S_STUDIO_KEYCLOAK_CLIENT_ID
  )
fi

for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    printf 'Required local setting is empty: %s\n' "$name" >&2
    exit 1
  fi
done

certificate_paths=(
  K8S_STUDIO_PII_ENGINE_CLIENT_CERT
  K8S_STUDIO_PII_ENGINE_CLIENT_KEY
  K8S_STUDIO_PII_ENGINE_CA_CERT
  K8S_STUDIO_OPENSEARCH_CA_CERT
)

for name in "${certificate_paths[@]}"; do
  path="${!name:-}"
  if [[ -n "$path" && ! -r "$path" ]]; then
    printf 'Configured certificate path is not readable (%s): %s\n' "$name" "$path" >&2
    exit 1
  fi
done

cd "$ROOT_DIR"
uv run --project apps/api python -c \
  'from k8s_stack_studio.config.settings import Settings; Settings()'
node apps/web/scripts/write-runtime-env.mjs apps/web/public/env.js
exec pnpm dev
