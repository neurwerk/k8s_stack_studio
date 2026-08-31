"use client";

import { useEffect, useState } from "react";
import { UserTable } from "@/components/user-table";
import { fetchUsers } from "@/lib/api/admin";
import { useIsKeycloakAdmin } from "@/lib/auth/roles";
import type { KeycloakUser } from "@/lib/api/admin";

export default function UsersPage() {
  const isAdmin = useIsKeycloakAdmin();
  const [users, setUsers] = useState<KeycloakUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!isAdmin) {
      setLoading(false);
      return () => { cancelled = true; };
    }
    setLoading(true);
    setError(null);

    fetchUsers(search || undefined)
      .then((data) => {
        if (!cancelled) setUsers(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isAdmin, search]);

  if (!isAdmin) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
          <p className="font-semibold">Access Denied</p>
          <p className="mt-1">
            You need the <code className="rounded bg-red-100 px-1">keycloak-admin</code> role to view users.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <input
          type="text"
          placeholder="Search users…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); }}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      <UserTable users={users} loading={loading} error={error} />
    </div>
  );
}
