"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchClients } from "@/lib/api/admin";
import { useIsKeycloakAdmin } from "@/lib/auth/roles";
import type { KeycloakClient } from "@/lib/api/admin";

export default function ClientsPage() {
  const isAdmin = useIsKeycloakAdmin();
  const [clients, setClients] = useState<KeycloakClient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [first, setFirst] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    if (!isAdmin) {
      setLoading(false);
      return () => {
        controller.abort();
      };
    }
    setLoading(true);
    setError(null);

    fetchClients(first, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) {
          setClients(page.items);
          setHasMore(page.has_more);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Unable to load clients. Please try again.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [isAdmin, first]);

  if (!isAdmin) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
          <p className="font-semibold">Access Denied</p>
          <p className="mt-1">
            You need the <code className="rounded bg-red-100 px-1">keycloak-admin</code> role to
            view clients.
          </p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-muted-foreground animate-pulse">Loading clients…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      </div>
    );
  }

  if (clients.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center text-muted-foreground">
          <p className="text-sm font-medium">No clients found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">OIDC Clients</h1>
      <p className="mb-4 text-sm text-muted-foreground">
        Read-only public and confidential client metadata. Secrets are never shown.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="px-4 py-3 font-medium">Client ID</th>
              <th className="px-4 py-3 font-medium">Name</th>
              <th className="px-4 py-3 font-medium">Description</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Access type</th>
            </tr>
          </thead>
          <tbody>
            {clients.map((client) => (
              <tr
                key={client.id}
                className="border-b border-border transition-colors hover:bg-muted/50"
              >
                <td className="px-4 py-3 font-mono text-xs font-medium">
                  <Link href={`/clients/${client.id}`} className="hover:underline">
                    {client.client_id}
                  </Link>
                </td>
                <td className="px-4 py-3">{client.name || "—"}</td>
                <td className="px-4 py-3 text-muted-foreground">{client.description || "—"}</td>
                <td className="px-4 py-3">
                  {client.enabled ? (
                    <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">
                      Enabled
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">
                      Disabled
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {client.public ? "Public" : "Confidential"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
