"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchMcpCatalog, fetchMcpConnection, fetchMcpConnections, mcpError } from "@/lib/api/mcp";
import type { McpCatalogEntry, McpConnectionStatus } from "@/lib/api/mcp";
import { ApiRequestError } from "@/lib/api/client";
import { useVerifiedSession } from "@/lib/auth/session-context";
import { McpTable } from "@/components/mcp-table";

export default function McpPage() {
  const session = useVerifiedSession();
  if (!session.mcp_catalog_available) {
    return <p className="p-6 text-sm text-muted-foreground">MCP integrations are not enabled.</p>;
  }
  return (
    <McpCatalog
      key={JSON.stringify([session.subject, session.agentgateway_roles])}
      connectionsEnabled={!!session.mcp_connections_available}
    />
  );
}

function McpCatalog({ connectionsEnabled }: { connectionsEnabled: boolean }) {
  const [items, setItems] = useState<McpCatalogEntry[]>([]);
  const [revisions, setRevisions] = useState<Record<string, number>>({});
  const [pendingRefresh, setPendingRefresh] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [connections, setConnections] = useState<Record<string, McpConnectionStatus>>({});
  const [checking, setChecking] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [retryUntil, setRetryUntil] = useState(0);
  const active = useRef(false);
  const inFlight = useRef(false);
  const refreshing = useRef(new Map<string, Promise<void>>());
  const connectionVersions = useRef<Record<string, number>>({});

  function refreshIntegration(id: string): Promise<void> {
    const pending = refreshing.current.get(id);
    if (pending) return pending;
    setPendingRefresh((previous) => ({ ...previous, [id]: true }));
    connectionVersions.current[id] = (connectionVersions.current[id] ?? 0) + 1;
    const operation = refreshOne(id).finally(() => {
      refreshing.current.delete(id);
      if (active.current) setPendingRefresh((previous) => ({ ...previous, [id]: false }));
    });
    refreshing.current.set(id, operation);
    return operation;
  }

  async function refreshOne(id: string) {
    const results = await Promise.allSettled([
      fetchMcpCatalog(),
      connectionsEnabled && items.find((item) => item.id === id)?.authentication_model ===
        "individual-authentication" ? fetchMcpConnection(id) : Promise.resolve(null),
    ]);
    if (!active.current) return;
    const [catalog, connection] = results;
    if (catalog.status === "fulfilled") {
      setItems((previous) => previous.flatMap((item) => {
        if (item.id !== id) return [item];
        const updated = catalog.value.find((entry) => entry.id === id);
        return updated ? [updated] : [];
      }));
      setError("");
    } else {
      setItems((previous) => previous.map((item) => item.id === id ? {
        ...item, publication: { state: "unavailable", checked_at: null, error_code: null },
      } : item));
    }
    if (connection.status === "fulfilled" && connection.value) {
      const value = connection.value;
      setConnections((previous) => ({ ...previous, [id]: value }));
      setConnectionError("");
    } else if (connection.status === "rejected") {
      setConnections((previous) => ({ ...previous, [id]: {
        status: "status unavailable", checked_at: null, retry_after: null,
        message: mcpError(connection.reason),
      } }));
    }
    setRevisions((previous) => ({ ...previous, [id]: (previous[id] ?? 0) + 1 }));
  }

  const refreshConnections = useCallback(async () => {
    if (!connectionsEnabled || inFlight.current || Date.now() < retryUntil) return;
    inFlight.current = true;
    const versions = { ...connectionVersions.current };
    setChecking(true);
    setConnectionError("");
    try {
      const result = await fetchMcpConnections();
      if (active.current) {
        setConnections((previous) =>
          Object.fromEntries(
            Object.entries(result).map(([id, value]) => [
              id,
              (versions[id] ?? 0) !== (connectionVersions.current[id] ?? 0) && previous[id]
                ? previous[id]
                : value.status === "status unavailable" && previous[id]
                ? { ...previous[id], message: value.message, retry_after: value.retry_after }
                : value,
            ]),
          ),
        );
        const seconds = Math.max(
          0,
          ...Object.values(result).map((value) => value.retry_after ?? 0),
        );
        if (seconds) setRetryUntil(Date.now() + seconds * 1000);
      }
    } catch (error) {
      if (active.current) {
        setConnectionError(mcpError(error));
        if (error instanceof ApiRequestError && error.status === 429) {
          setRetryUntil(Date.now() + (error.retryAfter ?? 60) * 1000);
        }
      }
    } finally {
      inFlight.current = false;
      if (active.current) setChecking(false);
    }
  }, [connectionsEnabled, retryUntil]);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  useEffect(() => {
    if (!retryUntil) return;
    const timeout = window.setTimeout(
      () => {
        setRetryUntil(0);
      },
      Math.max(0, retryUntil - Date.now()),
    );
    return () => {
      window.clearTimeout(timeout);
    };
  }, [retryUntil]);

  useEffect(() => {
    let cancelled = false;
    fetchMcpCatalog()
      .then((result) => {
        if (!cancelled) {
          setItems(result);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load integrations.");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  // One account verification for all personal rows; tool checks use the page queue.
  const initialRefresh = useRef(refreshConnections);
  useEffect(() => {
    void initialRefresh.current();
  }, []);

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-semibold">MCP integrations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Approved checks run automatically. Expand an integration to view tools and details.
        </p>
      </div>
      {loading && (
        <p role="status" className="text-sm text-muted-foreground">
          Loading integrations…
        </p>
      )}
      {error && (
        <div role="alert" className="alert alert-error">
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => {
              setError("");
              setLoading(true);
              setRefresh((value) => value + 1);
            }}
          >
            Retry
          </button>
        </div>
      )}
      {!loading &&
        !error &&
        (items.length ? (
          <McpTable
            items={items}
            connections={connections}
            revisions={revisions}
            pendingRefresh={pendingRefresh}
            connectionsEnabled={connectionsEnabled}
            checking={checking}
            connectionError={connectionError}
            onRefresh={refreshIntegration}
          />
        ) : (
          <p className="text-sm text-muted-foreground">No verified integrations are currently available.</p>
        ))}
    </div>
  );
}
