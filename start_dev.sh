#!/usr/bin/env bash
# Isolated local Compose environment. No cluster access or imported secrets.
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
action="${1:-up}"
case "$action" in
  up|setup|stop|down|logs|ps) ;;
  *) printf 'Usage: ./start_dev.sh [up [--detach]|setup|stop|down|logs|ps]\n' >&2; exit 2 ;;
esac
if ! docker --context default info >/dev/null 2>&1; then
  printf 'Docker default context is unavailable. Start Docker first.\n' >&2
  exit 1
fi
python3 "$root/dev/init-env.py"
compose=(docker --context default compose --project-name studio-dev \
  --env-file "$root/.dev-local/credentials.env" -f "$root/docker-compose.dev.yaml")
case "$action" in
  stop|down|ps) exec "${compose[@]}" "$action" ;;
  logs) exec "${compose[@]}" logs --follow api web ;;
esac
"${compose[@]}" config --quiet
"${compose[@]}" build api web pii-sim
"${compose[@]}" up --detach --wait postgres keycloak
"${compose[@]}" run --rm --no-deps keycloak-setup
if [[ "$action" == setup ]]; then exit 0; fi
"${compose[@]}" up --detach --wait --no-deps bridge pii-sim usage-sim logs-sim api web
printf '\nStudio: http://localhost:3001 | Keycloak: http://localhost:4081\n'
printf 'Users: developer, viewer, no-access. Password: DEV_USER_PASSWORD in .dev-local/credentials.env\n'
if [[ "${2:-}" == --detach || "${2:-}" == -d ]]; then exit 0; fi
trap '"${compose[@]}" stop' EXIT
"${compose[@]}" logs --follow api web
