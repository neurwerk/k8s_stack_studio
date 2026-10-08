"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchMcpCatalog, fetchMcpConnection, fetchMcpConnections, mcpError } from "@/lib/api/mcp";
import type { McpCatalogEntry, McpConnectionStatus } from "@/lib/api/mcp";
import { ApiRequestError } from "@/lib/api/client";
import { useVerifiedSession } from "@/lib/auth/session-context";
import { McpTable } from "@/components/mcp-table";
import { afterDiscovery } from "@/lib/mcp-checks";
import { McpRefresh, waitForMcpRetry } from "@/lib/mcp-refresh";

type RefreshResult = [PromiseSettledResult<McpCatalogEntry[]>, PromiseSettledResult<McpConnectionStatus | null>];

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
  const [statusRetryUntil, setStatusRetryUntil] = useState<Record<string, number>>({});
  const active = useRef(false);
  const inFlight = useRef(false);
  const refreshing = useRef(new Map<string, McpRefresh<RefreshResult | null>>());
  const connectionVersions = useRef<Record<string, number>>({});
  const publicationAfter = useRef<Record<string, string>>({});
  const statusRetryDeadline = useRef<Record<string, number>>({});
  const connectionRetryDeadline = useRef(0);

  function refreshIntegration(id: string, discoveredAt?: string): Promise<void> {
    if (discoveredAt) publicationAfter.current[id] = discoveredAt;
    setPendingRefresh((previous) => ({ ...previous, [id]: true }));
    connectionVersions.current[id] = (connectionVersions.current[id] ?? 0) + 1;
    let controller = refreshing.current.get(id);
    if (!controller) {
      controller = new McpRefresh();
      refreshing.current.set(id, controller);
    }
    return controller.request(() => readIntegration(id), (results) => { acceptIntegration(id, results); }).finally(() => {
      if (active.current && !controller.busy) setPendingRefresh((previous) => ({ ...previous, [id]: false }));
    });
  }

  async function readIntegration(id: string): Promise<RefreshResult | null> {
    const mounted = () => active.current;
    await waitForMcpRetry(Math.max(connectionRetryDeadline.current, statusRetryDeadline.current[id] ?? 0));
    if (!mounted()) return null;
    const results: RefreshResult = await Promise.allSettled([
      fetchMcpCatalog(),
      connectionsEnabled && items.find((item) => item.id === id)?.authentication_model ===
        "individual-authentication" ? fetchMcpConnection(id) : Promise.resolve(null),
    ]);
    // Even a superseded response can impose a rate limit on the follow-up read.
    const seconds = Math.max(0, ...results.map((result) => result.status === "rejected" &&
      result.reason instanceof ApiRequestError && result.reason.status === 429 ? result.reason.retryAfter ?? 60 : 0),
      results[1].status === "fulfilled" ? results[1].value?.retry_after ?? 0 : 0);
    if (seconds) {
      const deadline = Math.max(statusRetryDeadline.current[id] ?? 0, Date.now() + seconds * 1000);
      statusRetryDeadline.current[id] = deadline;
      if (mounted()) setStatusRetryUntil((previous) => ({ ...previous, [id]: deadline }));
    }
    return results;
  }

  function acceptIntegration(id: string, results: RefreshResult | null) {
    if (!active.current || !results) return;
    const [catalog, connection] = results;
    if (catalog.status === "fulfilled") {
      setItems((previous) => previous.flatMap((item) => {
        if (item.id !== id) return [item];
        const updated = catalog.value.find((entry) => entry.id === id);
        return updated ? [afterDiscovery(updated, publicationAfter.current[id])] : [];
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
      const seconds = connection.reason instanceof ApiRequestError && connection.reason.status === 429
        ? connection.reason.retryAfter ?? 60 : 0;
      setConnections((previous) => ({ ...previous, [id]: {
        status: "status unavailable", checked_at: null, retry_after: seconds || null,
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
        if (seconds) {
          connectionRetryDeadline.current = Date.now() + seconds * 1000;
          setRetryUntil(connectionRetryDeadline.current);
        }
      }
    } catch (error) {
      if (active.current) {
        setConnectionError(mcpError(error));
        if (error instanceof ApiRequestError && error.status === 429) {
          connectionRetryDeadline.current = Date.now() + (error.retryAfter ?? 60) * 1000;
          setRetryUntil(connectionRetryDeadline.current);
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
            statusRetryUntil={statusRetryUntil}
            connectionRetryUntil={retryUntil}
            onRefresh={refreshIntegration}
          />
        ) : (
          <p className="text-sm text-muted-foreground">No verified integrations are currently available.</p>
        ))}
    </div>
  );
}
