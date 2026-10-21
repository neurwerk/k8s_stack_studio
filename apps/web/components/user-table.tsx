"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, UserIcon } from "lucide-react";
import Link from "next/link";
import type { KeycloakUser, RecentSignins, UserSortKey } from "@/lib/api/admin";
import { UserStatus } from "@/components/user-status";

interface UserTableProps {
  users: KeycloakUser[];
  loading: boolean;
  error: string | null;
  activity?: RecentSignins | null;
  activityLoading?: boolean;
  sort: { key: UserSortKey; direction: "asc" | "desc" } | null;
  onSort: (key: UserSortKey) => void;
}

function SortHeader({ label, column, sort, onSort }: {
  label: string;
  column: UserSortKey;
  sort: UserTableProps["sort"];
  onSort: (column: UserSortKey) => void;
}) {
  const active = sort?.key === column;
  const direction = active ? sort.direction : null;
  return <th scope="col" aria-sort={direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none"}
    className="px-3 py-2">
    <button type="button" onClick={() => { onSort(column); }}
      aria-label={`Sort all users by ${label} ${direction === "asc" ? "descending" : "ascending"}`}
      className="flex w-full items-center gap-1 rounded text-left hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary">
      <span>{label}</span>
      {direction === "asc" ? <ArrowUp className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        : direction === "desc" ? <ArrowDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          : <ArrowUpDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
    </button>
  </th>;
}

export function UserTable({ users, loading, error, activity, activityLoading, sort, onSort }: UserTableProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-muted-foreground animate-pulse">Loading users…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="alert alert-error text-sm" role="alert">
        {error}
      </div>
    );
  }

  if (users.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <UserIcon className="mb-2 h-8 w-8" />
        <p className="text-sm">No users found</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="table w-full text-left text-sm">
        <thead className="border-b border-border bg-muted/50 text-xs uppercase text-muted-foreground">
          <tr>
            <SortHeader label="Username" column="username" sort={sort} onSort={onSort} />
            <SortHeader label="Email" column="email" sort={sort} onSort={onSort} />
            <SortHeader label="First Name" column="firstName" sort={sort} onSort={onSort} />
            <SortHeader label="Last Name" column="lastName" sort={sort} onSort={onSort} />
            <SortHeader label="Status" column="status" sort={sort} onSort={onSort} />
            <SortHeader label="Recent sign-in" column="recentSignin" sort={sort} onSort={onSort} />
          </tr>
        </thead>
        <tbody className="text-xs">
          {users.map((user) => (
            <tr
              key={user.id}
              className="border-b border-border transition-colors hover:bg-muted/50"
            >
              <td className="px-3 py-1.5 align-top">
                <Link
                  href={`/users/${user.id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {user.username}
                </Link>
              </td>
              <td className="px-3 py-1.5 align-top text-muted-foreground">{user.email || "—"}</td>
              <td className="px-3 py-1.5 align-top text-muted-foreground">{user.firstName || "—"}</td>
              <td className="px-3 py-1.5 align-top text-muted-foreground">{user.lastName || "—"}</td>
              <td className="px-3 py-1.5 align-top">
                <UserStatus user={user} />
              </td>
              <td className="px-3 py-1.5 align-top text-muted-foreground">
                {activityLoading ? (
                  "Loading sign-in..."
                ) : (
                  <SigninTime activity={activity} userId={user.id} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SigninTime({ activity, userId }: { activity?: RecentSignins | null; userId: string }) {
  const record = activity?.users[userId];
  if (!record || record.status === "unavailable") return <>Unavailable</>;
  if (record.status === "no_record") return <>No record in last 7 days</>;
  const instant = new Date(record.timestamp ?? "");
  const end = new Date(activity?.window_end ?? "");
  if (!Number.isFinite(instant.getTime()) || !Number.isFinite(end.getTime()))
    return <>Unavailable</>;
  const seconds = Math.max(0, Math.floor((end.getTime() - instant.getTime()) / 1000));
  const unit =
    seconds >= 86400 ? "day" : seconds >= 3600 ? "hour" : seconds >= 60 ? "minute" : "second";
  const divisor = unit === "day" ? 86400 : unit === "hour" ? 3600 : unit === "minute" ? 60 : 1;
  const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
    -Math.floor(seconds / divisor),
    unit,
  );
  const exact = instant.toISOString().replace("T", " ").replace("Z", " UTC");
  return (
    <time dateTime={instant.toISOString()} title={exact} aria-label={`${relative}; ${exact}`}>
      {relative}
    </time>
  );
}
