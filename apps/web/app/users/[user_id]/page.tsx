"use client";

import { ArrowLeft, Loader2, UserIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiKeyManager } from "@/components/api-key-manager";
import { UserUsage } from "@/components/user-usage";
import { fetchUser } from "@/lib/api/admin";
import {
  useCurrentUserId,
  useHasRole,
  useIsApiKeyAdmin,
  useIsKeycloakAdmin,
} from "@/lib/auth/roles";
import type { KeycloakUser } from "@/lib/api/admin";

export default function UserDetailPage() {
  const params = useParams();
  const userId = params.user_id as string;
  const currentUserId = useCurrentUserId();
  const isKeycloakAdmin = useIsKeycloakAdmin();
  const isApiKeyAdmin = useIsApiKeyAdmin();
  const isUsageAdmin = useHasRole("langfuse-admin");

  const [user, setUser] = useState<KeycloakUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isSelf = currentUserId === userId;
  const canViewProfile = isSelf || isKeycloakAdmin;
  const canManageKeys = isSelf || isApiKeyAdmin;
  const canViewUsage = isSelf || isUsageAdmin;

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

  // 403
  if (!canViewProfile && !canManageKeys && !canViewUsage) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
          <p className="font-semibold">Access Denied</p>
          <p className="mt-1">You do not have permission to view this user's profile.</p>
          {isKeycloakAdmin && (
            <Link
              href="/users"
              className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-red-700 underline hover:no-underline"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to users
            </Link>
          )}
        </div>
      </div>
    );
  }

  if (canViewProfile && loading && !canManageKeys && !canViewUsage) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (canViewProfile && error && !canManageKeys && !canViewUsage) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
          <p className="font-semibold">Error</p>
          <p className="mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (canViewProfile && !loading && !error && !user && !canManageKeys && !canViewUsage) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        User not found
      </div>
    );
  }

  return (
    <div className="p-6">
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
        <div className="rounded-lg border border-border bg-card p-6">
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
              {user.enabled ? (
                <span className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
                  Active
                </span>
              ) : (
                <span className="inline-flex items-center rounded-full bg-red-100 px-3 py-1 text-xs font-medium text-red-700">
                  Disabled
                </span>
              )}
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-muted-foreground">Email</p>
              <p>{user.email || "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Email Verified</p>
              <p>{user.emailVerified ? "Yes" : "No"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">User ID</p>
              <p className="font-mono text-xs">{user.id}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Created</p>
              <p>{new Date(user.createdTimestamp).toLocaleDateString()}</p>
            </div>
          </div>
        </div>
      ) : canManageKeys ? (
        <div className="rounded-lg border border-border bg-card p-6">
          <h1 className="text-xl font-semibold">API key management</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage API keys for user <span className="break-all font-mono text-xs">{userId}</span>.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card p-6">
          <h1 className="text-xl font-semibold">User usage</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Usage for user <span className="break-all font-mono text-xs">{userId}</span>.
          </p>
        </div>
      )}

      {(user || canManageKeys) && (
        <ApiKeyManager userId={user?.id ?? userId} canManage={canManageKeys} />
      )}
      {canViewUsage && <UserUsage userId={user?.id ?? userId} />}
    </div>
  );
}
