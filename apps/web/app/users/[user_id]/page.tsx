"use client";

import { UserStatus } from "@/components/user-status";

import { ArrowLeft, Loader2, UserIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiKeyManager } from "@/components/api-key-manager";
import { UserAccess } from "@/components/user-access";
import { fetchOwnGroups, fetchUser, fetchUserAccess } from "@/lib/api/admin";
import {
  useCurrentUserId,
  useIsApiKeyAdmin,
  useIsKeycloakAdmin,
  useUserRoles,
} from "@/lib/auth/roles";
import type { AdminUserAccess, KeycloakUser, UserGroups } from "@/lib/api/admin";

function visibleRoles(roles: string[]): string[] {
  return [...new Set(roles.filter((role) =>
    role !== "offline_access" && role !== "uma_authorization" &&
    !role.startsWith("default-roles-")))].sort();
}

export default function UserDetailPage() {
  const params = useParams();
  const userId = params.user_id as string;
  const currentUserId = useCurrentUserId();
  const isKeycloakAdmin = useIsKeycloakAdmin();
  const isApiKeyAdmin = useIsApiKeyAdmin();
  const ownRoles = useUserRoles();

  const [user, setUser] = useState<KeycloakUser | null>(null);
  const [accessResult, setAccessResult] = useState<{ userId: string; data: AdminUserAccess } | null>(null);
  const [accessErrorUserId, setAccessErrorUserId] = useState<string | null>(null);
  const [ownGroupsResult, setOwnGroupsResult] = useState<{ userId: string; data: UserGroups } | null>(null);
  const [ownGroupsErrorUserId, setOwnGroupsErrorUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isSelf = currentUserId === userId;
  const canViewProfile = isSelf || isKeycloakAdmin;
  const canManageKeys = isSelf || isApiKeyAdmin;

  useEffect(() => {
    if (!canViewProfile) {
      setLoading(false);
      return;
    }

    fetchUser(userId)
      .then((data) => {
        setUser(data);
      })
      .catch(() => {
        setError("Unable to load the user profile. Please try again.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [userId, canViewProfile]);

  useEffect(() => {
    if (!isKeycloakAdmin) return;
    let cancelled = false;
    void fetchUserAccess(userId)
      .then((data) => {
        if (!cancelled) {
          setAccessResult({ userId, data });
          setAccessErrorUserId(null);
        }
      })
      .catch(() => {
        if (!cancelled) setAccessErrorUserId(userId);
      });
    return () => { cancelled = true; };
  }, [isKeycloakAdmin, userId]);

  useEffect(() => {
    if (!isSelf || isKeycloakAdmin) return;
    let cancelled = false;
    void fetchOwnGroups()
      .then((data) => {
        if (!cancelled) {
          setOwnGroupsResult({ userId, data });
          setOwnGroupsErrorUserId(null);
        }
      })
      .catch(() => {
        if (!cancelled) setOwnGroupsErrorUserId(userId);
      });
    return () => { cancelled = true; };
  }, [isSelf, isKeycloakAdmin, userId]);

  const access = accessResult?.userId === userId ? accessResult.data : null;
  const ownGroups = ownGroupsResult?.userId === userId ? ownGroupsResult.data : null;
  const groups = isKeycloakAdmin ? access?.groups : ownGroups?.groups;
  const groupsTruncated = isKeycloakAdmin ? access?.groups_truncated : ownGroups?.groups_truncated;
  const groupsUnavailable = (isKeycloakAdmin ? accessErrorUserId : ownGroupsErrorUserId) === userId;
  const roles = visibleRoles(isSelf ? ownRoles : access?.effective_realm_roles.map((role) => role.name) ?? []);

  // 403
  if (!canViewProfile && !canManageKeys) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="alert alert-error max-w-md flex-col p-6 text-center text-sm">
          <p className="font-semibold">Access Denied</p>
          <p className="mt-1">You do not have permission to view this user's profile.</p>
          {isKeycloakAdmin && (
            <Link
              href="/users"
              className="mt-3 inline-flex items-center gap-1 text-sm font-medium underline hover:no-underline"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to users
            </Link>
          )}
        </div>
      </div>
    );
  }

  if (canViewProfile && loading && !canManageKeys) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (canViewProfile && error && !canManageKeys) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="alert alert-error max-w-md block p-6 text-sm" role="alert">
          <p className="font-semibold">Error</p>
          <p className="mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (canViewProfile && !loading && !error && !user && !canManageKeys) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        User not found
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6">
      {isKeycloakAdmin && (
        <div className="mb-6">
          <Link
            href="/users"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Users
          </Link>
        </div>
      )}

      {user ? (
        <div className="card border border-border bg-card p-6">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <UserIcon className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h1 className="text-xl font-semibold">
                {user.firstName} {user.lastName}
              </h1>
              <p className="text-sm text-muted-foreground">@{user.username}</p>
            </div>
            <div className="ml-auto">
              <UserStatus user={user} />
            </div>
          </div>

          <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <p className="text-muted-foreground">Email</p>
              <p>{user.email || "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">User ID</p>
              <p className="font-mono text-xs">{user.id}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Roles</p>
              {roles.length > 0 ? (
                <ul className="mt-1 flex flex-wrap gap-1.5">
                  {roles.map((role) => (
                     <li key={role} className="badge badge-ghost badge-sm text-xs">
                      {role}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-sm text-muted-foreground">
                  {!isSelf && !access && accessErrorUserId !== userId ? "Loading roles…" :
                    accessErrorUserId === userId ? "Unable to load roles." : "No roles assigned."}
                </p>
              )}
            </div>
            <div>
              <p className="text-muted-foreground">Created</p>
              <p>{new Date(user.createdTimestamp).toLocaleDateString()}</p>
            </div>
            <UserAccess groups={groups} groupsTruncated={groupsTruncated ?? false}
              error={groupsUnavailable} canViewGroup={isKeycloakAdmin} />
          </div>
        </div>
      ) : canManageKeys ? (
        <div className="card border border-border bg-card p-6">
          <h1 className="text-xl font-semibold">API key management</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage API keys for user <span className="break-all font-mono text-xs">{userId}</span>.
          </p>
        </div>
      ) : null}

      {(user || canManageKeys) && (
        <ApiKeyManager userId={user?.id ?? userId} canManage={canManageKeys} />
      )}
    </div>
  );
}
