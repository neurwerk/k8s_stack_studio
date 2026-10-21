# Architecture

## Browser and API

The [Next.js app](../../apps/web/app/) uses [the API client](../../apps/web/lib/api/client.ts) to call same-origin `/api` paths with the user's OIDC bearer token. In local development, [Next.js rewrites](../../apps/web/next.config.ts) forward these requests to `STUDIO_API_URL`, defaulting to `http://localhost:4010`. In Base deployments, the [Studio HTTPRoute](https://github.com/neurwerk/k8s_stack_base/blob/main/charts/studio/web/templates/http-route.yaml) sends `/api/` directly to the API Service and other UI paths to the web Service.

The web container writes public `OIDC_AUTHORITY` and `OIDC_CLIENT_ID` settings into `/env.js` at startup. [OIDC settings](../../apps/web/lib/oidc/settings.ts) use `/auth/callback` for browser sign-in. The separate `/oauth/callback` endpoint handles configured MCP provider connections and reaches the API through Base routing.

[FastAPI's entry point](../../apps/api/src/k8s_stack_studio/main.py) registers controllers and starts shared outbound clients. The [client lifespan](../../apps/api/src/k8s_stack_studio/lib/http_client.py) keeps PII Engine, OpenSearch, AgentGateway, and enabled ContextForge/Langfuse clients separate. The API's default port is `4010`; separate commands run the internal management listener on `4090` and the mutual-TLS notice lookup on `4091`.

## Identity and permissions

[Authentication middleware](../../apps/api/src/k8s_stack_studio/lib/auth.py) validates Keycloak tokens and builds the principal from verified claims. Protected `/api/` requests require the `studio-user` realm role. [Controller dependencies](../../apps/api/src/k8s_stack_studio/lib/dependencies.py) enforce additional roles and ownership checks; hiding a UI action does not grant or deny API access.

The [browser guard](../../apps/web/components/auth-guard.tsx) fetches `/api/session` before admitting the user. UI role hooks consume this server-verified session. Keycloak owns the role assignments; Studio does not infer permissions from user-supplied identity headers.

| Operation | Additional boundary | Source |
| --- | --- | --- |
| Directory administration | `keycloak-admin`; selected profile reads allow the current user | [admin controller](../../apps/api/src/k8s_stack_studio/controllers/admin.py) |
| API-key management | Current user or `api-key-admin`; forwards caller credentials to the bridge | [API-key controller](../../apps/api/src/k8s_stack_studio/controllers/api_keys.py) |
| Policy inspection and testing | `pii-admin`, then workload mutual TLS to PII Engine | [policy controller](../../apps/api/src/k8s_stack_studio/controllers/policy_engine.py) |
| OpenSearch logs | `opensearch-admin` | [logs controller](../../apps/api/src/k8s_stack_studio/controllers/logs.py) |
| Usage | Own usage; other-user and aggregate reads require `langfuse-admin` | [usage controller](../../apps/api/src/k8s_stack_studio/controllers/usage.py) |
| Gateway overview | User view filtered by gateway permissions; administrative view requires `gateway-admin` | [gateway controller](../../apps/api/src/k8s_stack_studio/controllers/gateway.py) |
| MCP setup | `mcp-admin`; tool discovery also uses caller permissions and native connection rights | [setup controller](../../apps/api/src/k8s_stack_studio/controllers/mcp_setup.py) |

Public exceptions include `/api/version`, approved inspection-trust assets, and the GET OAuth popup callback. `/gateway/model-discovery` bypasses Studio sign-in middleware but verifies the original credential through the bridge and filters the catalog by invocation permissions. It is not an anonymous model list. See [model discovery](../../apps/api/src/k8s_stack_studio/controllers/model_discovery.py) and shared [authentication guidance](https://github.com/neurwerk/docs/blob/main/dev/authentication/README.md).

## Service and state ownership

Studio reads Base-produced gateway catalog, status, and public trust files; it does not own gateway routing or inspection signing keys. Policy tools call PII Engine to inspect and test policy candidates; the controller provides no policy-deployment endpoint.

[Notice storage](../../apps/api/src/k8s_stack_studio/notice_store.py) owns PostgreSQL migrations for user/key notice preferences and MCP setup state. Migrations run explicitly before serving traffic. The [private notice listener](../../apps/api/src/k8s_stack_studio/notice_internal.py) checks the extProc client certificate and returns effective display preferences, separately from the browser API.

MCP catalog, account onboarding, personal connections, and runtime setup are separately enabled features. With setup enabled, the [worker](../../apps/api/src/k8s_stack_studio/mcp_worker.py) processes database-backed operations. Studio stores tool selections and publication state, uses scoped OpenBao/Kubernetes access for shared credentials and activation, and coordinates with ContextForge. ContextForge retains personal provider connections and OAuth tokens. Feature prerequisites are enforced in [Settings](../../apps/api/src/k8s_stack_studio/config/settings.py); a visible UI page does not establish that its backing integration is enabled.
