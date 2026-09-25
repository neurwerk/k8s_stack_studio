"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchGroups } from "@/lib/api/admin";
import type { AdminGroup } from "@/lib/api/admin";
import { useIsKeycloakAdmin } from "@/lib/auth/roles";

export default function GroupsPage() {
  const isAdmin = useIsKeycloakAdmin();
  const [groups, setGroups] = useState<AdminGroup[]>([]);
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
        void fetchGroups(search || undefined, first, controller.signal)
          .then((page) => {
            if (!controller.signal.aborted) {
              setGroups(page.items);
              setHasMore(page.has_more);
            }
          })
          .catch(() => {
            if (!controller.signal.aborted) setError("Unable to load groups. Please try again.");
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
          <h1 className="text-2xl font-semibold tracking-tight">Groups</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Read-only Keycloak group hierarchy and access.
          </p>
        </div>
        <input
          aria-label="Search groups"
          placeholder="Search groups…"
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
              <th className="px-4 py-3">Group</th>
              <th className="px-4 py-3">Path</th>
              <th className="px-4 py-3">Subgroups</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <tr key={group.id} className="border-b border-border last:border-0 hover:bg-muted/50">
                <td className="px-4 py-3 font-medium">
                  <Link className="hover:underline" href={`/groups/${group.id}`}>
                    {group.name}
                  </Link>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{group.path}</td>
                <td className="px-4 py-3">{group.subgroup_count}</td>
              </tr>
            ))}
            {!loading && !error && !groups.length && (
              <tr>
                <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                  No groups found.
                </td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                  Loading groups…
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
