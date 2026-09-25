#!/usr/bin/env bash
set -euo pipefail
umask 077
realm=studio-dev
config_dir="$(mktemp -d)"
trap 'rm -rf "$config_dir"' EXIT
kc() { /opt/keycloak/bin/kcadm.sh "$@" --config "$config_dir/config.json"; }
kc config credentials --server http://keycloak:8080 --realm master \
  --user bootstrap-admin --password "$KEYCLOAK_ADMIN_PASSWORD"

if kc get "realms/$realm" >/dev/null 2>&1; then
  kc update "realms/$realm" -s enabled=true -s sslRequired=none -s eventsEnabled=true
else
  kc create realms -s realm="$realm" -s enabled=true -s sslRequired=none \
    -s registrationAllowed=false -s eventsEnabled=true
fi

for role in studio-user pii-admin opensearch-admin keycloak-admin api-key-admin langfuse-admin; do
  if ! kc get "roles/$role" -r "$realm" >/dev/null 2>&1; then
    kc create roles -r "$realm" -s name="$role"
  fi
done

client_id="$(kc get clients -r "$realm" -q clientId=studio --fields id --format csv --noquotes)"
if [[ -n "$client_id" ]]; then
  kc update "clients/$client_id" -r "$realm" -f /opt/dev/studio-client.json
else
  client_id="$(kc create clients -r "$realm" -f /opt/dev/studio-client.json -i)"
fi
kc get client-scopes -r "$realm" --fields id,name --format csv --noquotes |
  while IFS=, read -r scope_id scope_name; do
    case "$scope_name" in
      basic|web-origins|acr|roles|profile|email)
        kc update "clients/$client_id/default-client-scopes/$scope_id" -r "$realm" -n ;;
    esac
  done
if ! kc get "clients/$client_id/protocol-mappers/models" -r "$realm" \
  --fields name --format csv --noquotes | grep -Fxq studio-dev-bridge-audience; then
  kc create "clients/$client_id/protocol-mappers/models" -r "$realm" \
    -f /opt/dev/bridge-audience.json
fi

bridge_id="$(kc get clients -r "$realm" -q clientId=studio-dev-bridge --fields id --format csv --noquotes)"
if [[ -z "$bridge_id" ]]; then
  bridge_id="$(kc create clients -r "$realm" -s clientId=studio-dev-bridge \
    -s enabled=true -s publicClient=false -s serviceAccountsEnabled=true \
    -s standardFlowEnabled=false -s directAccessGrantsEnabled=false \
    -s secret="$BRIDGE_CLIENT_SECRET" -i)"
else
  kc update "clients/$bridge_id" -r "$realm" -s secret="$BRIDGE_CLIENT_SECRET" \
    -s enabled=true -s serviceAccountsEnabled=true
fi

gateway_id="$(kc get clients -r "$realm" -q clientId=agentgateway --fields id --format csv --noquotes)"
if [[ -z "$gateway_id" ]]; then
  gateway_id="$(kc create clients -r "$realm" -s clientId=agentgateway \
    -s enabled=true -s publicClient=false -s standardFlowEnabled=false -i)"
fi
for role in llm:invoke model:demo-model:invoke; do
  if ! kc get "clients/$gateway_id/roles/$role" -r "$realm" >/dev/null 2>&1; then
    kc create "clients/$gateway_id/roles" -r "$realm" -s name="$role"
  fi
done

realm_management_id="$(kc get clients -r "$realm" -q clientId=realm-management --fields id --format csv --noquotes)"
account_id="$(kc get clients -r "$realm" -q clientId=account --fields id --format csv --noquotes)"
service_id="$(kc get "clients/$bridge_id/service-account-user" -r "$realm" --fields id --format csv --noquotes)"
kc add-roles -r "$realm" --uid "$service_id" --cid "$realm_management_id" \
  --rolename view-users --rolename query-users --rolename view-clients

developer_id=""
viewer_id=""
for name in developer viewer no-access; do
  user_id="$(kc get users -r "$realm" -q username="$name" -q exact=true --fields id --format csv --noquotes)"
  if [[ -z "$user_id" ]]; then
    user_id="$(kc create users -r "$realm" -s username="$name" -s enabled=true \
      -s firstName="$name" -s lastName=Demo -s email="$name@studio.test" \
      -s emailVerified=true -i)"
    kc set-password -r "$realm" --userid "$user_id" --new-password "$DEV_USER_PASSWORD"
  fi
  if [[ "$name" == no-access ]]; then continue; fi
  if [[ "$name" == developer ]]; then developer_id="$user_id"; fi
  if [[ "$name" == viewer ]]; then viewer_id="$user_id"; fi
  kc add-roles -r "$realm" --uid "$user_id" --rolename studio-user
  kc add-roles -r "$realm" --uid "$user_id" --cid "$account_id" --rolename view-groups
  if [[ "$name" == developer ]]; then
    kc add-roles -r "$realm" --uid "$user_id" --rolename pii-admin \
      --rolename opensearch-admin --rolename keycloak-admin \
      --rolename api-key-admin --rolename langfuse-admin
    kc add-roles -r "$realm" --uid "$user_id" --cid "$realm_management_id" \
      --rolename view-users --rolename query-users --rolename view-realm \
      --rolename view-clients --rolename view-events
    kc add-roles -r "$realm" --uid "$user_id" --cid "$gateway_id" \
      --rolename llm:invoke --rolename model:demo-model:invoke
  fi
done

# Local Keycloak has no LDAP connector. Mirror three representative child paths
# so both demo accounts exercise the same full-path group display as synced users.
ensure_group() {
  local parent_id="$1" group_name="$2" id
  if [[ -z "$parent_id" ]]; then
    id="$(kc get groups -r "$realm" -q search="$group_name" \
      --fields id,name --format csv --noquotes |
      while IFS=, read -r candidate_id candidate_name; do
        if [[ "$candidate_name" == "$group_name" ]]; then
          printf '%s\n' "$candidate_id"
          break
        fi
      done)"
    if [[ -z "$id" ]]; then id="$(kc create groups -r "$realm" -s name="$group_name" -i)"; fi
  else
    id="$(kc get "groups/$parent_id/children" -r "$realm" -q search="$group_name" \
      --fields id,name --format csv --noquotes |
      while IFS=, read -r candidate_id candidate_name; do
        if [[ "$candidate_name" == "$group_name" ]]; then
          printf '%s\n' "$candidate_id"
          break
        fi
      done)"
    if [[ -z "$id" ]]; then
      id="$(kc create "groups/$parent_id/children" -r "$realm" -s name="$group_name" -i)"
    fi
  fi
  printf '%s\n' "$id"
}

access_id="$(ensure_group '' access)"
for mapping in \
  'neurwerk-librechat-users:SG_neurwerk-librechat-users' \
  'neurwerk-studio-users:SG_neurwerk-studio-users' \
  'neurwerk-llm-all-users:SG_neurwerk-llm-allusers'; do
  parent_name="${mapping%%:*}"
  child_name="${mapping#*:}"
  parent_id="$(ensure_group "$access_id" "$parent_name")"
  child_id="$(ensure_group "$parent_id" "$child_name")"
  kc update "users/$developer_id/groups/$child_id" -r "$realm" -n
  kc update "users/$viewer_id/groups/$child_id" -r "$realm" -n
done
printf '{"developer":"%s","viewer":"%s"}\n' "$developer_id" "$viewer_id" \
  > /opt/studio-users/usage-users.json
printf 'Studio development realm, clients, roles and accounts are ready.\n'
