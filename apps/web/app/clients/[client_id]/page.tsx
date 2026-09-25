"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { RoleList, RoleMappings } from "@/components/role-mappings";
import { fetchClientAccess } from "@/lib/api/admin";
import type { AdminClientAccess } from "@/lib/api/admin";
import { useIsKeycloakAdmin } from "@/lib/auth/roles";

export default function ClientDetailPage() {
  const isAdmin = useIsKeycloakAdmin();
  const clientId = useParams().client_id as string;
  const [detail, setDetail] = useState<AdminClientAccess | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    void fetchClientAccess(clientId)
      .then(setDetail)
      .catch(() => {
        setError("Unable to load this client.");
      });
  }, [clientId, isAdmin]);

  if (!isAdmin)
    return (
      <div className="flex h-full items-center justify-center text-sm text-error">
        The keycloak-admin role is required.
      </div>
    );
  if (error) return <div className="alert alert-error m-6 text-sm" role="alert">{error}</div>;
  if (!detail) return <div className="p-6 text-sm text-muted-foreground">Loading client…</div>;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <Link
        href="/clients"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Clients
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">{detail.client.client_id}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {detail.client.description || detail.client.name || "OIDC client"}
        </p>
        <div className="mt-2 flex gap-2 text-xs">
          <span className="badge badge-ghost">
            {detail.client.public ? "Public" : "Confidential"}
          </span>
          <span className="badge badge-ghost">
            {detail.client.enabled ? "Enabled" : "Disabled"}
          </span>
          {detail.client.service_accounts_enabled && (
            <span className="badge badge-ghost">Service account</span>
          )}
        </div>
      </div>
      <section className="card border border-border bg-card p-4 sm:p-6">
        <h2 className="mb-1 text-lg font-semibold">Roles defined by this client</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          These roles exist for this application. Their existence does not assign them to anyone.
        </p>
        <RoleList roles={detail.defined_roles} />
        {detail.roles_truncated && (
          <p className="mt-2 text-xs text-muted-foreground">Only the first 100 roles are shown.</p>
        )}
      </section>
      <section className="card border border-border bg-card p-4 sm:p-6">
        <h2 className="mb-1 text-lg font-semibold">Roles allowed into tokens</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Direct role scope mappings for this client.
          {detail.client.full_scope_allowed
            ? " Full scope is enabled, so Keycloak may allow additional roles."
            : ""}
        </p>
        <RoleMappings mappings={detail.token_scope_roles} />
      </section>
      <section className="card border border-border bg-card p-4 sm:p-6">
        <h2 className="mb-1 text-lg font-semibold">Service account assignments</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Roles directly assigned to the client service account.
        </p>
        {detail.service_account_roles ? (
          <RoleMappings mappings={detail.service_account_roles} />
        ) : (
          <p className="text-sm text-muted-foreground">This client has no service account.</p>
        )}
      </section>
    </div>
  );
}
