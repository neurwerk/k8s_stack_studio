/** Typed API wrappers for admin and user-control endpoints. */

import { apiGet, apiPost } from "@/lib/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Raw user object from Keycloak Admin API. */
export interface KeycloakUser {
  id: string;
  username: string;
  email?: string | null;
  firstName: string;
  lastName: string;
  enabled?: boolean | null;
  emailVerified?: boolean | null;
  createdTimestamp: number;
}

/** Safe OIDC client metadata returned by Studio. */
export interface KeycloakClient {
  id: string;
  client_id: string;
  name: string;
  description: string;
  enabled: boolean;
  public: boolean;
  service_accounts_enabled: boolean;
  full_scope_allowed: boolean;
}

export interface AdminPage<T> {
  items: T[];
  first: number;
  max: number;
  has_more: boolean;
}

export interface AdminRole {
  id: string;
  name: string;
  description: string;
  composite: boolean;
}

export interface AdminGroup {
  id: string;
  name: string;
  path: string;
  subgroup_count: number;
}

export interface AdminClientRoles {
  id: string;
  client_id: string;
  roles: AdminRole[];
}

export interface AdminRoleMappings {
  realm_roles: AdminRole[];
  clients: AdminClientRoles[];
}

export interface AdminUserAccess {
  groups: AdminGroup[];
  groups_truncated: boolean;
  direct: AdminRoleMappings;
  effective_realm_roles: AdminRole[];
}

export interface AdminGroupDetail {
  group: AdminGroup;
  subgroups: AdminGroup[];
  subgroups_truncated: boolean;
  members: { id: string; username: string; email: string }[];
  members_truncated: boolean;
  direct: AdminRoleMappings;
  effective_realm_roles: AdminRole[];
}

export interface AdminClientAccess {
  client: KeycloakClient;
  defined_roles: AdminRole[];
  roles_truncated: boolean;
  token_scope_roles: AdminRoleMappings;
  service_account_roles: AdminRoleMappings | null;
}

/** An API key managed by the keycloak-api-key-bridge. */
export interface ApiKey {
  id: string;
  key_prefix: string;
  name: string;
  created_at: string;
  expires_at: string;
  permissions: string[];
  revoked: boolean;
}

/** Response from creating a new API key (includes the full key). */
export interface ApiKeyCreated {
  id: string;
  api_key: string;
  key_prefix: string;
  permissions: string[];
}

export interface CreateApiKeyRequest {
  name: string;
  permissions: string[];
  expires_in_days: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function invalidResponse(): never {
  throw new Error("The server returned an invalid response.");
}

function parseApiKey(value: unknown): ApiKey {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.key_prefix !== "string" ||
    typeof value.name !== "string" ||
    typeof value.created_at !== "string" ||
    typeof value.expires_at !== "string" ||
    !isStringArray(value.permissions) ||
    typeof value.revoked !== "boolean"
  ) {
    return invalidResponse();
  }
  return {
    id: value.id,
    key_prefix: value.key_prefix,
    name: value.name,
    created_at: value.created_at,
    expires_at: value.expires_at,
    permissions: value.permissions,
    revoked: value.revoked,
  };
}

function parseCreatedApiKey(value: unknown): ApiKeyCreated {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.api_key !== "string" ||
    typeof value.key_prefix !== "string" ||
    !isStringArray(value.permissions)
  ) {
    return invalidResponse();
  }
  return {
    id: value.id,
    api_key: value.api_key,
    key_prefix: value.key_prefix,
    permissions: value.permissions,
  };
}

// ── Endpoints ─────────────────────────────────────────────────────────────────

/** Fetch the current user's JWT claims from the backend. */
export function fetchMe(): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>("/me");
}

/** List all Keycloak users (keycloak-admin role required). */
export function fetchUsers(
  search?: string,
  first = 0,
  signal?: AbortSignal,
): Promise<KeycloakUser[]> {
  const params: Record<string, string> = { first: String(first), max: "25" };
  if (search) params.search = search;
  return apiGet<KeycloakUser[]>("/admin/users", params, signal);
}

export interface RecentSignin {
  status: "recorded" | "no_record" | "unavailable";
  timestamp: string | null;
}

export interface RecentSignins {
  window_start: string;
  window_end: string;
  users: Record<string, RecentSignin>;
}

export function fetchRecentSignins(
  userIds: string[],
  signal?: AbortSignal,
): Promise<RecentSignins> {
  const params = new URLSearchParams();
  userIds.forEach((id) => {
    params.append("user_ids", id);
  });
  return apiGet<RecentSignins>("/admin/recent-signins", params, signal);
}

/** Fetch a single Keycloak user by ID (self or keycloak-admin). */
export function fetchUser(userId: string): Promise<KeycloakUser> {
  return apiGet<KeycloakUser>(`/admin/users/${userId}`);
}

/** List viewable OIDC clients (keycloak-admin role required). */
export function fetchClients(first = 0, signal?: AbortSignal): Promise<AdminPage<KeycloakClient>> {
  return apiGet<AdminPage<KeycloakClient>>(
    "/admin/clients",
    { first: String(first), max: "25" },
    signal,
  );
}

export function fetchGroups(
  search?: string,
  first = 0,
  signal?: AbortSignal,
): Promise<AdminPage<AdminGroup>> {
  const params: Record<string, string> = { first: String(first), max: "25" };
  if (search) params.search = search;
  return apiGet<AdminPage<AdminGroup>>("/admin/groups", params, signal);
}

export function fetchGroup(groupId: string): Promise<AdminGroupDetail> {
  return apiGet<AdminGroupDetail>(`/admin/groups/${encodeURIComponent(groupId)}`);
}

export function fetchRealmRoles(
  search?: string,
  first = 0,
  signal?: AbortSignal,
): Promise<AdminPage<AdminRole>> {
  const params: Record<string, string> = { first: String(first), max: "25" };
  if (search) params.search = search;
  return apiGet<AdminPage<AdminRole>>("/admin/roles", params, signal);
}

export function fetchUserAccess(userId: string): Promise<AdminUserAccess> {
  return apiGet<AdminUserAccess>(`/admin/users/${encodeURIComponent(userId)}/access`);
}

export function fetchClientAccess(clientId: string): Promise<AdminClientAccess> {
  return apiGet<AdminClientAccess>(`/admin/clients/${encodeURIComponent(clientId)}/access`);
}

/** List API keys for a user (self or api-key-admin). */
export function fetchApiKeys(userId: string): Promise<ApiKey[]> {
  return apiGet<unknown>(`/users/${userId}/api-keys`).then((response) => {
    if (!Array.isArray(response)) return invalidResponse();
    return response.map(parseApiKey);
  });
}

/** Fetch the target user's current AgentGateway permissions. */
export function fetchAgentGatewayPermissions(userId: string): Promise<string[]> {
  return apiGet<unknown>(`/users/${userId}/agentgateway-permissions`).then((response) => {
    if (!isRecord(response) || !isStringArray(response.permissions)) return invalidResponse();
    return response.permissions;
  });
}

/** Create a new API key for a user (self or api-key-admin). */
export function createApiKey(userId: string, body: CreateApiKeyRequest): Promise<ApiKeyCreated> {
  return apiPost<CreateApiKeyRequest, unknown>(`/users/${userId}/api-keys`, body).then(
    parseCreatedApiKey,
  );
}

/** Revoke an API key (self or api-key-admin). */
export function revokeApiKey(userId: string, keyId: string): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>, Record<string, unknown>>(
    `/users/${userId}/api-keys/${keyId}/revoke`,
    {},
  );
}
