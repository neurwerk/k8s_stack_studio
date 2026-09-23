"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RoleList, RoleMappings } from "@/components/role-mappings";
import { fetchUserAccess } from "@/lib/api/admin";
import type { AdminUserAccess } from "@/lib/api/admin";

export function UserAccess({ userId }: { userId: string }) {
  const [access, setAccess] = useState<AdminUserAccess | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    void fetchUserAccess(userId)
      .then(setAccess)
      .catch(() => {
        setError(true);
      });
  }, [userId]);

  return (
    <section className="mt-6 rounded-lg border border-border p-4">
      <h2 className="text-lg font-semibold">Access</h2>
      <p className="mb-4 text-sm text-muted-foreground">
        Read-only Keycloak memberships and roles.
      </p>
      {error && <p className="text-sm text-red-700">Unable to load access information.</p>}
      {!error && !access && <p className="text-sm text-muted-foreground">Loading access…</p>}
      {access && (
        <div className="space-y-6">
          <div>
            <h3 className="mb-2 font-medium">Group memberships</h3>
            {!access.groups.length && <p className="text-sm text-muted-foreground">None</p>}
            <div className="flex flex-wrap gap-2">
              {access.groups.map((group) => (
                <Link
                  key={group.id}
                  href={`/groups/${group.id}`}
                  className="rounded border border-border bg-muted px-2 py-1 font-mono text-xs hover:bg-muted/70"
                >
                  {group.path}
                </Link>
              ))}
            </div>
            {access.groups_truncated && (
              <p className="mt-2 text-xs text-muted-foreground">
                Only the first 25 groups are shown.
              </p>
            )}
          </div>
          <div>
            <h3 className="mb-1 font-medium">Direct role assignments</h3>
            <p className="mb-3 text-sm text-muted-foreground">
              Attached directly to this user, not through a group.
            </p>
            <RoleMappings mappings={access.direct} />
          </div>
          <div>
            <h3 className="mb-1 font-medium">Effective realm roles</h3>
            <p className="mb-3 text-sm text-muted-foreground">
              Includes roles received through groups and composite roles. Application roles above
              show direct assignments only.
            </p>
            <RoleList roles={access.effective_realm_roles} />
          </div>
        </div>
      )}
    </section>
  );
}
