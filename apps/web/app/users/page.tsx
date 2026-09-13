"use client";

import { useEffect, useState } from "react";
import { UserTable } from "@/components/user-table";
import { fetchRecentSignins, fetchUsers } from "@/lib/api/admin";
import { useIsKeycloakAdmin } from "@/lib/auth/roles";
import type { KeycloakUser, RecentSignins } from "@/lib/api/admin";

export default function UsersPage() {
  const isAdmin = useIsKeycloakAdmin();
  const [users, setUsers] = useState<KeycloakUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [first, setFirst] = useState(0);
  const [activity, setActivity] = useState<RecentSignins | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    if (!isAdmin) {
      setLoading(false);
      return () => {
        controller.abort();
      };
    }
    setLoading(true);
    setError(null);
    setActivity(null);
    setActivityLoading(false);
    const timer = setTimeout(
      () => {
        void fetchUsers(search || undefined, first, signal)
          .then(async (data) => {
            if (signal.aborted) return;
            setUsers(data);
            setLoading(false);
            if (!data.length) return;
            setActivityLoading(true);
            try {
              const result = await fetchRecentSignins(
                data.map((user) => user.id),
                signal,
              );
              if (!signal.aborted) setActivity(result);
            } catch {
              // Event permissions or availability must not hide the user page.
              if (!signal.aborted) setActivity(null);
            } finally {
              if (!signal.aborted) setActivityLoading(false);
            }
          })
          .catch(() => {
            if (!signal.aborted) {
              setError("Unable to load users. Please try again.");
              setLoading(false);
            }
          });
      },
      search ? 300 : 0,
    );

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [isAdmin, search, first]);

  if (!isAdmin) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
          <p className="font-semibold">Access Denied</p>
          <p className="mt-1">
            You need the <code className="rounded bg-red-100 px-1">keycloak-admin</code> role to
            view users.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <input
          type="text"
          aria-label="Search users"
          placeholder="Search users…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setFirst(0);
          }}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      <p className="mb-4 text-sm text-muted-foreground">
        Recent sign-in is the latest recorded successful Keycloak login across all clients in the
        last 7 days, relative to the last lookup. History may be limited by retention or event
        collection. No record does not mean the user has never signed in.
      </p>
      <UserTable
        users={users}
        loading={loading}
        error={error}
        activity={activity}
        activityLoading={activityLoading}
      />
      <div className="mt-4 flex items-center gap-4 text-sm">
        <button
          className="rounded border border-border px-3 py-1.5 disabled:opacity-50"
          disabled={loading || first === 0}
          onClick={() => {
            setFirst(Math.max(0, first - 25));
          }}
        >
          Previous
        </button>
        <span>Page {first / 25 + 1}</span>
        <button
          className="rounded border border-border px-3 py-1.5 disabled:opacity-50"
          disabled={loading || !!error || users.length < 25}
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
