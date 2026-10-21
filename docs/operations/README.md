# Operations

## Configuration and deployment owners

Base's [Studio charts](https://github.com/neurwerk/k8s_stack_base/tree/main/charts/studio) own Services, HTTP routing, certificates, network access, Secret references, and process startup. Client repositories select the compatible platform release and values. Tooling owns credential provisioning through the shared [OpenBao procedure](https://github.com/neurwerk/docs/blob/main/dev/operations/openbao.md).

[API Settings](../../apps/api/src/k8s_stack_studio/config/settings.py) load environment variables, normally prefixed `K8S_STUDIO_`; dependency injection caches settings per process. Change deployment configuration through its owner and restart affected processes through the deployment workflow. Browser OIDC values are written at web-container startup by [the entrypoint](../../apps/web/docker-entrypoint.sh).

| Input | Required wiring |
| --- | --- |
| Browser identity | `OIDC_AUTHORITY`, `OIDC_CLIENT_ID`, and matching Keycloak redirect/logout URLs |
| API identity | `K8S_STUDIO_KEYCLOAK_SERVER_URL`, `K8S_STUDIO_KEYCLOAK_REALM`, `K8S_STUDIO_KEYCLOAK_CLIENT_ID`; production uses authenticated mode |
| PII Engine | HTTPS URL plus `K8S_STUDIO_PII_ENGINE_CA_CERT`, `K8S_STUDIO_PII_ENGINE_CLIENT_CERT`, and `K8S_STUDIO_PII_ENGINE_CLIENT_KEY`; the API loads these files during startup |
| Key management | `K8S_STUDIO_KEYCLOAK_API_KEY_BRIDGE_URL`; identity and key permissions remain with Keycloak and the bridge |
| Logs and usage | OpenSearch URL, read credentials and CA settings; `K8S_STUDIO_AGENTGATEWAY_ADMIN_URL` and `K8S_STUDIO_USAGE_TIMEZONE` for gateway accounting |
| Studio database | `K8S_STUDIO_NOTICE_DATABASE_URL`, or the `K8S_STUDIO_NOTICE_POSTGRES_*` fields; required by Base's notice service and by MCP setup |
| Gateway files | `STUDIO_GATEWAY_CATALOG_FILE`, optional `STUDIO_GATEWAY_STATUS_FILE`, and configured `STUDIO_GATEWAY_TRUST_FILE`; these aliases have no `K8S_STUDIO_` prefix |
| Personal activity | `K8S_STUDIO_LLM_LOGS_ENABLED` plus the Langfuse URL and project keys when enabled |
| MCP | Matching catalog, team/role IDs, trusted service identity, HTTPS origins, and feature flags from compatible Base configuration; setup also needs database, publication file, and scoped workload identities |

Use [Base's API deployment template](https://github.com/neurwerk/k8s_stack_base/blob/main/charts/studio/api/templates/deployment.yaml) for the complete mapping. It runs `k8s-stack-studio-migrate` in an init container, then starts API, management, and notice processes separately. The API image's default command starts only the application API. The migration is transactional and rejects a database schema newer than the image supports.

## Verification and diagnosis

For an authorized deployment, verify these distinct boundaries:

| Observation | Meaning and next check |
| --- | --- |
| `/api/version` responds | Application API is serving; it does not prove downstream services are usable |
| Internal `4090/health` responds | Management process is alive; it performs no dependency checks |
| Sign-in succeeds but `/api/session` returns 403 | Check the user's `studio-user` admission role in Keycloak |
| A feature returns 403 | Check its [server-side permission boundary](../architecture/README.md#identity-and-permissions), not just sidebar visibility |
| Policy request returns 502 or 504 | Check the PII Engine endpoint, workload TLS mounts, and service availability; 504 indicates a timeout |
| Notice features are unavailable | Check the database configuration and migration init-container result; `/api/session` reports schema availability |
| Gateway observations are unknown | Check the publisher-owned status file and its matching catalog/policy revisions; desired configuration alone is not observed health |
| Configured trust readiness fails | Check the published bundle and `STUDIO_GATEWAY_TRUST_REQUIRED_VERSION`; the Base probe can request that exact immutable bundle |

The management listener exposes `/metrics`. Application and OAuth transport logging intentionally avoid access URLs and sensitive payloads. Inspect bounded service errors without enabling HTTP wire logging. For local process status and logs, use the [development launcher](../development/README.md#local-stack).

## Releases and recovery

[The release workflow](../../.github/workflows/build-push.yaml) accepts exact `vX.Y.Z` tags, checks matching API/Web/lockfile versions, runs the quality workflow, and publishes separate API and Web images with digest references in the GitHub Release. Follow shared [image release guidance](https://github.com/neurwerk/docs/blob/main/dev/operations/image-releases.md); Base owns adoption of the image pins.

Studio migrations are forward-only. Reverting an image does not undo the database schema or MCP publication effects. Recovery must use the selected release's supported path and account for Studio PostgreSQL state, shared credentials, and ContextForge-owned connections. Follow shared [upgrade and recovery guidance](https://github.com/neurwerk/docs/blob/main/dev/operations/upgrades.md) for compatibility, backup ownership, and post-deployment checks.
