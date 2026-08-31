"use client";

import { UserIcon } from "lucide-react";
import Link from "next/link";
import type { KeycloakUser } from "@/lib/api/admin";

interface UserTableProps {
  users: KeycloakUser[];
  loading: boolean;
  error: string | null;
}

export function UserTable({ users, loading, error }: UserTableProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-muted-foreground animate-pulse">Loading users…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
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
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="px-4 py-3 font-medium">Username</th>
            <th className="px-4 py-3 font-medium">Email</th>
            <th className="px-4 py-3 font-medium">First Name</th>
            <th className="px-4 py-3 font-medium">Last Name</th>
            <th className="px-4 py-3 font-medium">Status</th>
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
              <td className="px-4 py-3 text-muted-foreground">
                {user.email || "—"}
              </td>
              <td className="px-4 py-3 text-muted-foreground">
                {user.firstName || "—"}
              </td>
              <td className="px-4 py-3 text-muted-foreground">
                {user.lastName || "—"}
              </td>
              <td className="px-4 py-3">
                {user.enabled ? (
                  <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">
                    Active
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">
                    Disabled
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}