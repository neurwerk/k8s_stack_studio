"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { RoleList, RoleMappings } from "@/components/role-mappings";
import { fetchGroup } from "@/lib/api/admin";
import type { AdminGroupDetail } from "@/lib/api/admin";
import { useIsKeycloakAdmin } from "@/lib/auth/roles";

export default function GroupDetailPage() {
  const isAdmin = useIsKeycloakAdmin();
  const groupId = useParams().group_id as string;
  const [detail, setDetail] = useState<AdminGroupDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    void fetchGroup(groupId)
      .then(setDetail)
      .catch(() => {
        setError("Unable to load this group.");
      });
  }, [groupId, isAdmin]);

  if (!isAdmin)
    return (
      <div className="flex h-full items-center justify-center text-sm text-red-700">
        The keycloak-admin role is required.
      </div>
    );
  if (error) return <div className="p-6 text-sm text-red-700">{error}</div>;
  if (!detail) return <div className="p-6 text-sm text-muted-foreground">Loading group…</div>;

  return (
    <div className="space-y-6 p-6">
      <Link
        href="/groups"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Groups
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">{detail.group.name}</h1>
        <p className="font-mono text-xs text-muted-foreground">{detail.group.path}</p>
      </div>
      <section className="rounded-lg border border-border p-4">
        <h2 className="mb-3 text-lg font-semibold">Subgroups</h2>
        {!detail.subgroups.length && <p className="text-sm text-muted-foreground">None</p>}
        <div className="space-y-2">
          {detail.subgroups.map((group) => (
            <Link
              key={group.id}
              href={`/groups/${group.id}`}
              className="block rounded border border-border p-2 text-sm hover:bg-muted"
            >
              <span className="font-medium">{group.name}</span>
              <span className="ml-2 font-mono text-xs text-muted-foreground">{group.path}</span>
            </Link>
          ))}
        </div>
        {detail.subgroups_truncated && (
          <p className="mt-2 text-xs text-muted-foreground">
            Only the first 25 subgroups are shown.
          </p>
        )}
      </section>
      <section className="rounded-lg border border-border p-4">
        <h2 className="mb-3 text-lg font-semibold">Members</h2>
        {!detail.members.length && <p className="text-sm text-muted-foreground">None</p>}
        <div className="space-y-2">
          {detail.members.map((member) => (
            <Link
              key={member.id}
              href={`/users/${member.id}`}
              className="block rounded border border-border p-2 text-sm hover:bg-muted"
            >
              <span className="font-medium">{member.username}</span>
              {member.email && <span className="ml-2 text-muted-foreground">{member.email}</span>}
            </Link>
          ))}
        </div>
        {detail.members_truncated && (
          <p className="mt-2 text-xs text-muted-foreground">Only the first 25 members are shown.</p>
        )}
      </section>
      <section className="rounded-lg border border-border p-4">
        <h2 className="mb-1 text-lg font-semibold">Direct role assignments</h2>
        <p className="mb-4 text-sm text-muted-foreground">Roles attached directly to this group.</p>
        <RoleMappings mappings={detail.direct} />
      </section>
      <section className="rounded-lg border border-border p-4">
        <h2 className="mb-1 text-lg font-semibold">Effective realm roles</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Includes composite roles returned by Keycloak. Parent groups may grant additional access
          to members.
        </p>
        <RoleList roles={detail.effective_realm_roles} />
      </section>
    </div>
  );
}
