"use client";

import { KeyIcon, Loader2, Plus, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createApiKey,
  fetchAgentGatewayPermissions,
  fetchApiKeys,
  revokeApiKey,
} from "@/lib/api/admin";
import type { ApiKey, ApiKeyCreated } from "@/lib/api/admin";

interface ApiKeyManagerProps {
  userId: string;
  canManage: boolean;
}

const API_KEY_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._\x2d]{0,63}$/;

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unavailable" : date.toLocaleDateString();
}

export function ApiKeyManager({ userId, canManage }: ApiKeyManagerProps) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [permissionsLoading, setPermissionsLoading] = useState(false);
  const [permissionsError, setPermissionsError] = useState<string | null>(null);
  const [newKeyName, setNewKeyName] = useState("");
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [expiresInDays, setExpiresInDays] = useState("90");
  const [newKeyResult, setNewKeyResult] = useState<ApiKeyCreated | null>(null);
  const [createdExpiryDays, setCreatedExpiryDays] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const keyRequestId = useRef(0);
  const permissionRequestId = useRef(0);

  const loadKeys = useCallback(async () => {
    const requestId = ++keyRequestId.current;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchApiKeys(userId);
      if (requestId === keyRequestId.current) setKeys(data);
    } catch {
      if (requestId === keyRequestId.current)
        setError("Unable to load API keys. Please try again.");
    } finally {
      if (requestId === keyRequestId.current) setLoading(false);
    }
  }, [userId]);

  const loadPermissions = useCallback(async () => {
    const requestId = ++permissionRequestId.current;
    setPermissionsLoading(true);
    setPermissionsError(null);
    try {
      const data = await fetchAgentGatewayPermissions(userId);
      if (requestId === permissionRequestId.current) {
        setPermissions(data);
        setSelectedPermissions((current) =>
          current.filter((permission) => data.includes(permission)),
        );
      }
    } catch {
      if (requestId === permissionRequestId.current) {
        setPermissions([]);
        setSelectedPermissions([]);
        setPermissionsError("Unable to load available permissions. Please try again.");
      }
    } finally {
      if (requestId === permissionRequestId.current) setPermissionsLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void loadKeys();
    return () => {
      keyRequestId.current += 1;
    };
  }, [loadKeys]);

  useEffect(() => {
    permissionRequestId.current += 1;
    setShowCreateForm(false);
    setPermissions([]);
    setSelectedPermissions([]);
    setPermissionsError(null);
    setNewKeyResult(null);
    setCreatedExpiryDays(null);
  }, [userId]);

  const openCreateForm = () => {
    setShowCreateForm(true);
    setNewKeyResult(null);
    setPermissions([]);
    setSelectedPermissions([]);
    setPermissionsError(null);
    void loadPermissions();
  };

  const closeCreateForm = () => {
    permissionRequestId.current += 1;
    setShowCreateForm(false);
    setPermissionsLoading(false);
    setPermissionsError(null);
  };

  const expiry = Number(expiresInDays);
  const validExpiry = Number.isInteger(expiry) && expiry >= 1 && expiry <= 365;
  const validKeyName = API_KEY_NAME_PATTERN.test(newKeyName);
  const canCreate =
    validKeyName &&
    selectedPermissions.length > 0 &&
    validExpiry &&
    !permissionsLoading;

  const handleCreate = async () => {
    if (!canCreate) return;
    setCreating(true);
    setPermissionsError(null);
    try {
      const result = await createApiKey(userId, {
        name: newKeyName.trim(),
        permissions: selectedPermissions,
        expires_in_days: expiry,
      });
      setNewKeyResult(result);
      setCreatedExpiryDays(expiry);
      setNewKeyName("");
      closeCreateForm();
      await loadKeys();
    } catch {
      setPermissionsError("Unable to create the API key. Please try again.");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    setActionLoading(keyId);
    setError(null);
    try {
      await revokeApiKey(userId, keyId);
      await loadKeys();
    } catch {
      setError("Unable to revoke the API key. Please try again.");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <section className="mt-6" aria-labelledby="api-keys-heading">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id="api-keys-heading" className="text-lg font-semibold tracking-tight">
          API Keys
        </h2>
        {canManage && (
          <button
            type="button"
            onClick={openCreateForm}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Create API key
          </button>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => {
              void loadKeys();
            }}
            className="underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {showCreateForm && (
        <form
          className="mb-4 rounded-lg border border-border bg-muted/30 p-4"
          aria-describedby="api-key-immutable-help"
          onSubmit={(event) => {
            event.preventDefault();
            void handleCreate();
          }}
        >
          <h3 className="text-sm font-semibold">Create API key</h3>
          <p id="api-key-immutable-help" className="mt-1 text-sm text-muted-foreground">
            Permissions and expiry are immutable. Create a replacement key if these settings need to
            change.
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="api-key-name" className="mb-2 block text-sm font-medium">
                Key name
              </label>
              <input
                id="api-key-name"
                type="text"
                placeholder="e.g. deployment-cli"
                value={newKeyName}
                onChange={(event) => {
                  setNewKeyName(event.target.value);
                }}
                required
                maxLength={64}
                pattern={API_KEY_NAME_PATTERN.source}
                aria-describedby="api-key-name-help"
                aria-invalid={newKeyName !== "" && !validKeyName}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                autoFocus
              />
              <p id="api-key-name-help" className="mt-1 text-xs text-muted-foreground">
                Use 1 to 64 letters, numbers, periods, underscores, or hyphens. Start with a letter
                or number.
              </p>
            </div>
            <div>
              <label htmlFor="api-key-expiry" className="mb-2 block text-sm font-medium">
                Expiry (days)
              </label>
              <input
                id="api-key-expiry"
                type="number"
                min="1"
                max="365"
                required
                value={expiresInDays}
                onChange={(event) => {
                  setExpiresInDays(event.target.value);
                }}
                aria-describedby="api-key-expiry-help"
                aria-invalid={expiresInDays !== "" && !validExpiry}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <p id="api-key-expiry-help" className="mt-1 text-xs text-muted-foreground">
                Choose from 1 to 365 days.
              </p>
            </div>
          </div>

          <fieldset className="mt-4">
            <legend className="text-sm font-medium">Permissions</legend>
            {permissionsLoading && (
              <p
                className="mt-2 flex items-center gap-2 text-sm text-muted-foreground"
                aria-live="polite"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading available
                permissions...
              </p>
            )}
            {permissionsError && (
              <div
                role="alert"
                className="mt-2 flex flex-wrap items-center gap-2 text-sm text-destructive"
              >
                <span>{permissionsError}</span>
                <button
                  type="button"
                  onClick={() => {
                    void loadPermissions();
                  }}
                  className="underline hover:no-underline"
                >
                  Retry
                </button>
              </div>
            )}
            {!permissionsLoading && !permissionsError && permissions.length === 0 && (
              <p className="mt-2 text-sm text-muted-foreground">
                No permissions are currently available for this user.
              </p>
            )}
            {permissions.length > 0 && (
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {permissions.map((permission) => (
                  <label
                    key={permission}
                    className="flex items-center gap-2 rounded border border-border bg-background p-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={selectedPermissions.includes(permission)}
                      onChange={(event) => {
                        setSelectedPermissions((current) =>
                          event.target.checked
                            ? [...current, permission]
                            : current.filter((item) => item !== permission),
                        );
                      }}
                    />
                    <span className="break-all font-mono text-xs">{permission}</span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="submit"
              disabled={creating || !canCreate}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {creating && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              Create key
            </button>
            <button
              type="button"
              onClick={closeCreateForm}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {newKeyResult && (
        <div
          className="mb-4 rounded-lg border border-green-500/30 bg-green-500/5 p-4 text-sm text-green-700"
          role="status"
        >
          <p className="font-semibold">API key created</p>
          <p className="mt-2 break-all font-mono text-xs">{newKeyResult.api_key}</p>
          <p className="mt-2 text-xs">Permissions: {newKeyResult.permissions.join(", ")}</p>
          {createdExpiryDays !== null && (
            <p className="mt-1 text-xs">Expires in {createdExpiryDays} days.</p>
          )}
          <p className="mt-2 text-xs">Copy this key now. It will not be shown again.</p>
          <button
            type="button"
            onClick={() => {
              setNewKeyResult(null);
            }}
            className="mt-2 underline hover:no-underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {loading && (
          <div
            className="flex items-center justify-center py-8 text-muted-foreground"
            role="status"
            aria-live="polite"
        >
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> Loading API keys...
        </div>
      )}

      {!loading && keys.length === 0 && !error && !showCreateForm && (
        <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <KeyIcon className="mb-2 h-8 w-8" aria-hidden="true" />
          <p className="text-sm">No API keys yet</p>
        </div>
      )}

      {!loading && keys.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[700px] text-left text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th scope="col" className="px-3 py-2 font-medium">
                  Name
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Key prefix
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Permissions
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Expires
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key.id} className="border-b border-border last:border-0 hover:bg-muted/50">
                  <td className="px-3 py-2 font-medium">{key.name}</td>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                    {key.key_prefix}...
                  </td>
                  <td className="max-w-64 px-3 py-2 font-mono text-xs break-words">
                    {key.permissions.join(", ")}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{formatDate(key.expires_at)}</td>
                  <td className="px-3 py-2">
                    {!key.revoked && canManage && (
                      <button
                        type="button"
                        onClick={() => {
                          void handleRevoke(key.id);
                        }}
                        disabled={actionLoading === key.id}
                        className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {actionLoading === key.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                        ) : (
                          <XCircle className="h-3 w-3" aria-hidden="true" />
                        )}
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
