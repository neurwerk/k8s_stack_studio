"use client";

import Link from "next/link";
import type { AdminGroup } from "@/lib/api/admin";

export function UserAccess({ groups, groupsTruncated, error, canViewGroup }: {
  groups?: AdminGroup[];
  groupsTruncated: boolean;
  error: boolean;
  canViewGroup: boolean;
}) {
  return (
    <section aria-label="Group memberships">
      <h2 className="text-sm font-normal text-muted-foreground">Groups</h2>
      {error ? (
        <p className="mt-3 text-sm text-destructive">Unable to load group memberships.</p>
      ) : groups === undefined ? (
        <p className="mt-3 text-sm text-muted-foreground">Loading groups…</p>
      ) : groups.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No group memberships.</p>
      ) : (
        <>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {groups.map((group) => (
              <li key={group.id} title={group.path}
                className="badge badge-ghost badge-sm h-auto max-w-full break-all text-xs">
                {canViewGroup ? (
                  <Link href={`/groups/${group.id}`} className="hover:underline">
                    {group.path.split("/").filter(Boolean).at(-1) ?? group.name}
                  </Link>
                ) : (
                  <span>{group.path.split("/").filter(Boolean).at(-1) ?? group.name}</span>
                )}
              </li>
            ))}
          </ul>
          {groupsTruncated && (
            <p className="mt-3 text-xs text-muted-foreground">Only the first 25 groups are shown.</p>
          )}
        </>
      )}
    </section>
  );
}
