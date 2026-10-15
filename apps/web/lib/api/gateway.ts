import { apiGet, ApiRequestError } from "@/lib/api/client";

export type HealthState = "available" | "unavailable" | "unknown";
export type CredentialSource = "company" | "caller_supplied" | "none";

export interface GatewayEndpoint {
  id: string;
  url: string;
  entry_mode: "api" | "forward_proxy";
  caller_auth_modes: ("oidc_bearer" | "neurwerk_bearer" | "proxy_basic")[];
}

export interface GatewayDestination {
  id: string;
  kind: "model" | "mcp" | "application";
  display_name: string;
  endpoint_ids: string[];
  profile_ids: string[];
  required_permissions: string[];
  credential_modes: { source: CredentialSource; required_permissions: string[] }[];
  provider_id: string | null;
  model: string | null;
}

export interface GatewayProfile {
  id: string;
  revision: string;
  limitations: string[];
  operations: {
    id: string;
    support: "supported" | "unsupported" | "unknown";
    restoration_scope: "request" | "persistent" | "none";
    limitations: string[];
    evidence_ref: string | null;
    verified_at: string | null;
  }[];
}

export interface GatewayView {
  catalog: {
    schema_version: 1;
    catalog_revision: string;
    policy_revision: string;
    endpoints: GatewayEndpoint[];
    destinations: GatewayDestination[];
    profiles: GatewayProfile[];
  };
  status: {
    state: "current" | "unknown";
    reason: "missing" | "invalid" | "stale" | "mismatch" | null;
    catalog_revision: string | null;
    applied_policy_revision: string | null;
    observed_at: string | null;
    valid_until: string | null;
    endpoints: { id: string; state: HealthState }[];
    profiles: { id: string; revision: string | null; state: HealthState }[];
  };
}

export interface TrustCertificate {
  fingerprint_sha256: string;
  purpose: "inspection-root";
  state: "active" | "transitional";
  not_before: string;
  not_after: string;
}

export interface TrustManifest {
  schema_version: 1;
  current_version: string;
  versions: {
    version: string;
    published_at: string;
    bundle_sha256: string;
    certificates: TrustCertificate[];
  }[];
}

export function fetchGateway(administrator: boolean, signal?: AbortSignal): Promise<GatewayView> {
  return apiGet<GatewayView>(administrator ? "/admin/gateway" : "/gateway", undefined, signal);
}

/** Public certificates use no session token or cookies and never a cached current pointer. */
export async function fetchGatewayTrust(signal?: AbortSignal): Promise<TrustManifest> {
  const response = await fetch("/api/gateway/trust/manifest.json", {
    signal, credentials: "omit", cache: "no-store",
  });
  if (!response.ok) throw ApiRequestError.fromResponse(response);
  return response.json() as Promise<TrustManifest>;
}
