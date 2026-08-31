#!/bin/sh
# =============================================================================
# Runtime entrypoint for the k8s-stack-studio-web image.
#
# Writes per-deployment OIDC configuration into a JS snippet served as a
# static asset (/env.js).  The Next.js app picks up the values from
# window.__ENV__ at runtime, so the same Docker image can be deployed to
# any environment without a rebuild.
#
# Expected env vars:
#   OIDC_AUTHORITY   - Keycloak / OIDC provider issuer URL
#   OIDC_CLIENT_ID   - OIDC client ID registered with the provider
# =============================================================================

set -e

ENV_JS="apps/web/public/env.js"

node /app/write-runtime-env.mjs "$ENV_JS"

exec node apps/web/server.js
