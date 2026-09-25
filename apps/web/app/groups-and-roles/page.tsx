"use client";

import { useIsKeycloakAdmin } from "@/lib/auth/roles";

export default function GroupsAndRolesPage() {
  const isAdmin = useIsKeycloakAdmin();

  if (!isAdmin) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-error">
        The keycloak-admin role is required.
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold tracking-tight">Groups and Roles</h1>
    </div>
  );
}
