"use client";

import { useVerifiedSession } from "@/lib/auth/session-context";

/** Return the current user's Keycloak UUID (the ``sub`` claim). */
export function useCurrentUserId(): string | null {
  return useVerifiedSession().subject;
}

/** Return the list of Keycloak realm roles for the current user. */
export function useUserRoles(): string[] {
  return useVerifiedSession().realm_roles;
}

/** Check whether the current user has a specific realm role. */
export function useHasRole(role: string): boolean {
  const roles = useUserRoles();
  return roles.includes(role);
}

/** Check whether the current user has the keycloak-admin role. */
export function useIsKeycloakAdmin(): boolean {
  const roles = useUserRoles();
  return roles.includes("keycloak-admin");
}

/** Check whether the current user has the api-key-admin role. */
export function useIsApiKeyAdmin(): boolean {
  const roles = useUserRoles();
  return roles.includes("api-key-admin");
}

/** Check whether the current user has the opensearch-admin role. */
export function useIsOpensearchAdmin(): boolean {
  const roles = useUserRoles();
  return roles.includes("opensearch-admin");
}

/** Check whether the current user may inspect and test PII policy. */
export function useIsPiiAdmin(): boolean {
  const roles = useUserRoles();
  return roles.includes("pii-admin");
}
