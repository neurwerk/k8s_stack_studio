"use client";

import { Fragment, useRef, useState, useEffect } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { McpConnection } from "@/components/mcp-connection";
import { fetchMcpTools, mcpError, runMcpCheck } from "@/lib/api/mcp";
import { ApiRequestError } from "@/lib/api/client";
import type {
  McpCatalogEntry,
  McpConnectionStatus,
  McpTool,
  McpCheckResult,
  McpCheck,
} from "@/lib/api/mcp";

interface TableProps {
  items: McpCatalogEntry[];
  connections: Record<string, McpConnectionStatus>;
  connectionsEnabled: boolean;
  checking: boolean;
  connectionError: string;
  retryBlocked: boolean;
  onRefresh: () => void;
}

export function McpTable(props: TableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="table w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            {["MCP", "Type", "Connection / last check", "Actions"].map((title) => (
              <th key={title} className="px-4 py-3 font-medium">
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.items.map((item) => (
            <McpRow key={item.id} item={item} {...props} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CheckedAt({ value }: { value: string }) {
  return (
    <time
      dateTime={value}
      title={new Date(value).toISOString()}
      className="block text-xs text-muted-foreground"
    >
      Checked {new Date(value).toLocaleString()}
    </time>
  );
}

function McpRow({
  item,
  connections,
  connectionsEnabled,
  checking,
  connectionError,
  retryBlocked,
  onRefresh,
}: TableProps & { item: McpCatalogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const [tools, setTools] = useState<McpTool[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastCheck, setLastCheck] = useState<McpCheckResult | null>(null);
  const [retryUntil, setRetryUntil] = useState(0);
  const active = useRef(true);
  const pending = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!retryUntil) return;
    const timer = window.setTimeout(() => { setRetryUntil(0); }, Math.max(0, retryUntil - Date.now()));
    return () => { window.clearTimeout(timer); };
  }, [retryUntil]);
  const personal = item.authentication_model === "individual-authentication";
  const connection = connections[item.id];
  const statusError = connectionError || connection?.message;

  async function loadTools() {
    if (pending.current || Date.now() < retryUntil) return;
    pending.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await fetchMcpTools(item.id);
      if (active.current) setTools(result);
    } catch (error) {
      if (active.current) {
        setError(mcpError(error));
        if (error instanceof ApiRequestError && error.status === 429)
          setRetryUntil(Date.now() + (error.retryAfter ?? 60) * 1000);
      }
    } finally {
      pending.current = false;
      if (active.current) setLoading(false);
    }
  }

  return (
    <Fragment>
      <tr className="border-b border-border align-top transition-colors hover:bg-muted/50">
        <td className="px-4 py-3">
          <button
            type="button"
            className="btn btn-ghost btn-sm -ml-2 whitespace-nowrap font-medium"
            disabled={!item.permitted}
            aria-expanded={expanded}
            aria-controls={`mcp-tools-${item.id}`}
            onClick={() => {
              setExpanded(!expanded);
              if (!expanded && tools === null) void loadTools();
            }}
          >
            {expanded ? (
              <ChevronDown size={16} aria-hidden />
            ) : (
              <ChevronRight size={16} aria-hidden />
            )}
            {item.name}
          </button>
        </td>
        <td className="px-4 py-3">
          <span className="badge badge-ghost badge-sm whitespace-nowrap">
            {item.authentication_model}
          </span>
        </td>
        <td className="min-w-56 space-y-1 px-4 py-3" aria-live="polite">
          {!item.permitted ? (
            <span className="text-muted-foreground">No permission</span>
          ) : (
            <>
              {personal && (
                <div>
                  <span
                    className={`badge badge-sm ${connection?.status === "connected" && !statusError ? "badge-success" : "badge-ghost"}`}
                  >
                    {statusError && connection ? "Last known: " : ""}
                    <span className="capitalize">
                      {connection?.status ?? (checking ? "Checking…" : "Status unavailable")}
                    </span>
                  </span>
                  {connection?.status === "refresh pending" && (
                    <p className="text-xs text-muted-foreground">
                      Refresh will be attempted on the next call.
                    </p>
                  )}
                  {statusError && (
                    <p role="alert" className="max-w-sm text-xs text-error">
                      {statusError}
                      {connection?.retry_after
                        ? ` Retry in ${String(connection.retry_after)} seconds.`
                        : ""}
                    </p>
                  )}
                </div>
              )}
              {!personal && (
                <p className="text-xs text-muted-foreground">
                  {item.authentication_model === "shared-authentication"
                    ? "Company-managed connection"
                    : "No provider sign-in needed"}
                </p>
              )}
              {lastCheck ? (
                <div>
                  <span
                    className={`badge badge-sm ${lastCheck.status === "passed" ? "badge-success" : "badge-error"}`}
                  >
                    {lastCheck.status === "passed" ? "Check passed" : "Check failed"}
                  </span>
                  {lastCheck.display_value !== null && (
                    <p className="break-words text-sm">
                      {lastCheck.display_label}: {lastCheck.display_value}
                    </p>
                  )}
                  <CheckedAt value={lastCheck.checked_at} />
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No tool check run yet</p>
              )}
            </>
          )}
        </td>
        <td className="px-4 py-3">
          {personal && item.permitted && connectionsEnabled && (
            <div className="flex flex-wrap gap-2">
              <McpConnection id={item.id} status={connection?.status} onRefresh={onRefresh} />
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={checking || retryBlocked}
                onClick={onRefresh}
              >
                {checking ? "Checking…" : "Check status"}
              </button>
            </div>
          )}
          {!item.permitted && (
            <span className="text-xs text-muted-foreground">Ask an operator for access</span>
          )}
        </td>
      </tr>
      <tr
        id={`mcp-tools-${item.id}`}
        hidden={!expanded}
        className="border-b border-border bg-muted/20"
      >
        <td colSpan={4} className="px-4 py-4 sm:px-8">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h2 className="font-medium">Available tools</h2>
            <button
              type="button"
              className="btn btn-xs btn-ghost"
              disabled={loading || !!retryUntil}
              onClick={() => void loadTools()}
            >
              Refresh tools
            </button>
          </div>
          {loading && (
            <p role="status" className="text-sm text-muted-foreground">
              Loading tools…
            </p>
          )}
          {error && (
            <p role="alert" className="mb-3 text-sm text-error">
              {error}
            </p>
          )}
          {!loading && !error && tools?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No approved tools are currently available.
            </p>
          )}
          {tools && (
            <table className="table w-full text-sm">
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>Description</th>
                  <th>Check</th>
                </tr>
              </thead>
              <tbody>
                {tools.map((tool) => (
                  <tr key={tool.name} className="align-top">
                    <td className="font-mono text-xs">{tool.name}</td>
                      <td className="max-w-xl whitespace-pre-wrap break-words">
                        <p className="line-clamp-3" title={tool.description}>
                          {tool.description || "—"}
                        </p>
                      </td>
                    <td className="min-w-64">
                      {Object.entries(tool.checks).length ? (
                        Object.entries(tool.checks).map(([id, check]) => (
                          <ToolCheck
                            key={id}
                            integration={item.id}
                            id={id}
                            check={check}
                            onResult={setLastCheck}
                          />
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">No check configured</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-3 text-xs text-muted-foreground">
            Tool lists may be cached. Run a configured check to verify a tool call with your access.
          </p>
        </td>
      </tr>
    </Fragment>
  );
}

function ToolCheck({
  integration,
  id,
  check,
  onResult,
}: {
  integration: string;
  id: string;
  check: McpCheck;
  onResult: (value: McpCheckResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<McpCheckResult | null>(null);
  const [error, setError] = useState("");
  const [retryUntil, setRetryUntil] = useState(0);
  const active = useRef(true);
  const pending = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!retryUntil) return;
    const timer = window.setTimeout(() => { setRetryUntil(0); }, Math.max(0, retryUntil - Date.now()));
    return () => { window.clearTimeout(timer); };
  }, [retryUntil]);

  async function run() {
    if (pending.current || Date.now() < retryUntil) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const value = await runMcpCheck(integration, id);
      if (active.current) {
        setResult(value);
        onResult(value);
      }
    } catch (error) {
      if (active.current) {
        setError(mcpError(error));
        onResult({
          status: "failed",
          checked_at: new Date().toISOString(),
          result: "",
          display_label: null,
          display_value: null,
        });
        if (error instanceof ApiRequestError && error.status === 429)
          setRetryUntil(Date.now() + (error.retryAfter ?? 60) * 1000);
      }
    } finally {
      pending.current = false;
      if (active.current) setBusy(false);
    }
  }

  return (
    <div className="mb-3 space-y-2">
      <button
        type="button"
        className="btn btn-sm btn-outline"
        disabled={busy || !!retryUntil}
        onClick={() => void run()}
      >
        {busy ? "Running…" : check.name}
      </button>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">Test parameters</summary>
        <pre className="mt-2 max-h-48 max-w-lg overflow-auto whitespace-pre-wrap break-all">
          {JSON.stringify(check.arguments, null, 2)}
        </pre>
      </details>
      {error && (
        <p role="alert" className="max-w-sm text-xs text-error">
          {error}
        </p>
      )}
      {result && (
        <div aria-live="polite">
          <span
            className={`badge badge-sm ${result.status === "passed" ? "badge-success" : "badge-error"}`}
          >
            {result.status === "passed" ? "Passed" : "Failed"}
          </span>
          <CheckedAt value={result.checked_at} />
          {result.result && (
            <details className="mt-2 text-xs">
              <summary className="cursor-pointer">Result</summary>
              <pre className="mt-2 max-h-64 max-w-xl overflow-auto whitespace-pre-wrap break-all rounded border border-border bg-card p-3">
                {result.result}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
