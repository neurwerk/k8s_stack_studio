"use client";

import { useEffect, useState } from "react";
import { fetchMcpCatalog } from "@/lib/api/mcp";
import type { McpCatalogEntry } from "@/lib/api/mcp";
import { useVerifiedSession } from "@/lib/auth/session-context";
import { McpConnection } from "@/components/mcp-connection";

const authenticationHelp = {
  "no-authentication": "No provider credential is needed.",
  "shared-authentication": "The operator manages the shared provider credential.",
  "individual-authentication": "Each user needs their own provider connection.",
};

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);

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
          setError(true);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-semibold">MCP integrations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Operator-approved integrations. Platform permission is separate from provider
          authentication.
        </p>
      </div>
      <div className="alert alert-info text-sm">
        {connectionsEnabled
          ? "Connect your own provider account. Operators manage registrations and tool discovery; connecting never grants platform access."
          : "This catalog is read-only. Provider connection status and Connect controls are not available yet. Operators manage registrations and tool discovery."}
      </div>
      {loading && (
        <p role="status" className="text-sm text-muted-foreground">
          Loading integrations…
        </p>
      )}
      {error && (
        <div role="alert" className="alert alert-error">
          <span>Could not load integrations.</span>
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => {
              setError(false);
              setLoading(true);
              setRefresh((value) => value + 1);
            }}
          >
            Retry
          </button>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <p className="text-sm text-muted-foreground">No integrations have been configured.</p>
      )}
      {!loading && !error && (
        <ul className="grid gap-4 lg:grid-cols-2">
          {items.map((item) => (
            <li key={item.id} className="card border border-border bg-card">
              <div className="card-body gap-3 p-5">
                <h2 className="card-title break-words text-lg">{item.name}</h2>
                <p className="break-words font-mono text-xs text-muted-foreground">
                  {item.authentication_model}
                </p>
                <p className="text-sm text-muted-foreground">
                  {authenticationHelp[item.authentication_model]}
                </p>
                <div className="flex flex-wrap gap-2">
                  <span className={`badge ${item.permitted ? "badge-success" : "badge-ghost"}`}>
                    {item.permitted ? "Invocation permitted" : "No permission"}
                  </span>
                  {item.connection_status &&
                    !(
                      connectionsEnabled &&
                      item.authentication_model === "individual-authentication" &&
                      item.permitted
                    ) && (
                      <span className="badge badge-warning">Status unavailable</span>
                    )}
                </div>
                {connectionsEnabled &&
                  item.authentication_model === "individual-authentication" &&
                  item.permitted && <McpConnection id={item.id} />}
                {!item.permitted && (
                  <p className="text-sm text-muted-foreground">
                    Ask an operator for platform access. A provider connection never grants
                    permission.
                  </p>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
