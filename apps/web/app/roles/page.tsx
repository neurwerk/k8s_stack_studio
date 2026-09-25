"use client";

import { useEffect, useState } from "react";
import { fetchRealmRoles } from "@/lib/api/admin";
import type { AdminRole } from "@/lib/api/admin";
import { useIsKeycloakAdmin } from "@/lib/auth/roles";

export default function RolesPage() {
  const isAdmin = useIsKeycloakAdmin();
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [search, setSearch] = useState("");
  const [first, setFirst] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    if (!isAdmin) {
      return () => {
        controller.abort();
      };
    }
    const timer = setTimeout(
      () => {
        setLoading(true);
        setError(null);
        void fetchRealmRoles(search || undefined, first, controller.signal)
          .then((page) => {
            if (!controller.signal.aborted) {
              setRoles(page.items);
              setHasMore(page.has_more);
            }
          })
          .catch(() => {
            if (!controller.signal.aborted)
              setError("Unable to load realm roles. Please try again.");
          })
          .finally(() => {
            if (!controller.signal.aborted) setLoading(false);
          });
      },
      search ? 300 : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [isAdmin, search, first]);

  if (!isAdmin)
    return (
      <div className="flex h-full items-center justify-center text-sm text-error">
        The keycloak-admin role is required.
      </div>
    );

  return (
    <div className="mx-auto max-w-[1600px] p-4 sm:p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Realm Roles</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Platform-wide roles. Application roles are shown under Clients.
          </p>
        </div>
        <input
          aria-label="Search realm roles"
          placeholder="Search roles…"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setFirst(0);
          }}
          className="input input-bordered bg-base-100 text-sm"
        />
      </div>
      {error && (
        <div className="alert alert-error mb-4 text-sm" role="alert">
          {error}
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="table w-full text-left text-sm">
          <thead className="border-b border-border text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Description</th>
              <th className="px-4 py-3">Type</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.id} className="border-b border-border last:border-0">
                <td className="px-4 py-3 font-mono text-xs font-medium">{role.name}</td>
                <td className="px-4 py-3 text-muted-foreground">{role.description || "—"}</td>
                <td className="px-4 py-3">{role.composite ? "Composite" : "Single role"}</td>
              </tr>
            ))}
            {!loading && !error && !roles.length && (
              <tr>
                <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                  No realm roles found.
                </td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                  Loading roles…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex items-center gap-4 text-sm">
        <button
          className="btn btn-outline btn-sm"
          disabled={loading || first === 0}
          onClick={() => {
            setFirst(Math.max(0, first - 25));
          }}
        >
          Previous
        </button>
        <span>Page {first / 25 + 1}</span>
        <button
          className="btn btn-outline btn-sm"
          disabled={loading || !!error || !hasMore}
          onClick={() => {
            setFirst(first + 25);
          }}
        >
          Next
        </button>
      </div>
    </div>
  );
}
