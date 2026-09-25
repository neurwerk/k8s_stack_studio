"use client";

import { UserIcon } from "lucide-react";
import Link from "next/link";
import type { KeycloakUser, RecentSignins } from "@/lib/api/admin";
import { UserStatus } from "@/components/user-status";

interface UserTableProps {
  users: KeycloakUser[];
  loading: boolean;
  error: string | null;
  activity?: RecentSignins | null;
  activityLoading?: boolean;
}

export function UserTable({ users, loading, error, activity, activityLoading }: UserTableProps) {
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
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="px-4 py-3 font-medium">Username</th>
            <th className="px-4 py-3 font-medium">Email</th>
            <th className="px-4 py-3 font-medium">First Name</th>
            <th className="px-4 py-3 font-medium">Last Name</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Recent sign-in</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr
              key={user.id}
              className="border-b border-border transition-colors hover:bg-muted/50"
            >
              <td className="px-4 py-3">
                <Link
                  href={`/users/${user.id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {user.username}
                </Link>
              </td>
              <td className="px-4 py-3 text-muted-foreground">{user.email || "—"}</td>
              <td className="px-4 py-3 text-muted-foreground">{user.firstName || "—"}</td>
              <td className="px-4 py-3 text-muted-foreground">{user.lastName || "—"}</td>
              <td className="px-4 py-3">
                <UserStatus user={user} />
              </td>
              <td className="px-4 py-3 text-muted-foreground">
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
