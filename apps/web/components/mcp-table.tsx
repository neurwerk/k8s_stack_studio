"use client";

import { Fragment, useState, useEffect } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { McpConnection } from "@/components/mcp-connection";
import { McpDiscovery } from "@/components/mcp-discovery";
import { fetchMcpTools, mcpError, runMcpCheck } from "@/lib/api/mcp";
import { ApiRequestError } from "@/lib/api/client";
import { McpChecks, checkSummary, skipReason } from "@/lib/mcp-checks";
import type { IntegrationChecks, CheckState } from "@/lib/mcp-checks";
import type { McpCatalogEntry, McpConnectionStatus, McpCheck } from "@/lib/api/mcp";

interface TableProps {
  items: McpCatalogEntry[];
  connections: Record<string, McpConnectionStatus>;
  revisions: Record<string, number>;
  pendingRefresh: Record<string, boolean>;
  connectionsEnabled: boolean;
  checking: boolean;
  connectionError: string;
  statusRetryUntil: Record<string, number>;
  connectionRetryUntil: number;
  onRefresh: (id: string, discoveredAt?: string) => Promise<void>;
}

export function McpTable(props: TableProps) {
  const [, render] = useState(0);
  const [checks] = useState(() => new McpChecks({
    tools: fetchMcpTools,
    check: runMcpCheck,
    error: (error) => ({
      message: mcpError(error),
      retryAfter: error instanceof ApiRequestError && error.status === 429 ? error.retryAfter ?? 60 : undefined,
    }),
  }));
  useEffect(() => {
    checks.start(() => { render((value) => value + 1); });
    return () => { checks.stop(); };
  }, [checks]);
  useEffect(() => {
    checks.sync(props.items, props.connectionError ? {} : props.connections, props.revisions, props.pendingRefresh);
  }, [checks, props.items, props.connections, props.connectionError, props.revisions, props.pendingRefresh]);

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="table w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            {["MCP", "Authentication", "Checks / account", "Actions"].map((title) => (
              <th key={title} className="px-4 py-3 font-medium">{title}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.items.map((item) => (
            <McpRow key={item.id} item={item} {...props} state={checks.states[item.id]}
              onRecheck={() => { checks.recheck(item.id); }} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CheckedAt({ value }: { value: string }) {
  const date = new Date(value);
  const today = date.toDateString() === new Date().toDateString();
  return (
    <time dateTime={value} title={date.toLocaleString()} className="block text-xs tabular-nums text-muted-foreground">
      Checked {date.toLocaleString(undefined, {
        ...(today ? {} : { month: "short", day: "numeric", year: "numeric" }),
        hour: "2-digit", minute: "2-digit",
      })}
    </time>
  );
}

function McpRow({ item, connections, connectionsEnabled, checking, connectionError, connectionRetryUntil, statusRetryUntil, onRefresh, pendingRefresh, state, onRecheck }:
  TableProps & { item: McpCatalogEntry; state?: IntegrationChecks; onRecheck: () => void }) {
  const [expanded, setExpanded] = useState(false);
  // A clock only unlocks the manual action. It never starts another check.
  const [now, setNow] = useState(() => Date.now());
  const retryUntil = Math.max(state?.retryUntil ?? 0, connectionRetryUntil, statusRetryUntil[item.id] ?? 0);
  useEffect(() => {
    if (!retryUntil) return;
    const timer = window.setTimeout(() => { setNow(Date.now()); }, Math.max(0, retryUntil - Date.now()));
    return () => { window.clearTimeout(timer); };
  }, [retryUntil]);
  const personal = item.authentication_model === "individual-authentication";
  const connection = connections[item.id];
  const reason = pendingRefresh[item.id] ? "Refreshing integration…" : skipReason(item, connectionError ? undefined : connection);
  const summary = checkSummary(state);
  const results = Object.values(state?.checks ?? {}).flatMap((check) => check.result ? [check.result] : []);
  const checkedAt = Object.values(state?.checks ?? {}).flatMap((check) => {
    const timestamp = check.result?.checked_at ?? check.checkedAt;
    return timestamp ? [timestamp] : [];
  }).sort().at(-1);
  const accounts = [...new Set(results.filter((result) => result.status === "passed" && result.display_value !== null)
    .map((result) => `${result.display_label ?? "Account"}: ${result.display_value ?? ""}`))];
  const label = checking && personal && !connection && !connectionError
    ? "Checking connection…" : reason || summary.label;
  const statusUnavailable = personal && connectionsEnabled &&
    (!!connectionError || !connection || !!connection.message || connection.status === "status unavailable");
  const unavailableErrors = [...new Set(Object.values(state?.checks ?? {}).flatMap((check) => check.error ? [check.error] : []))];

  return (
    <Fragment>
      <tr className="border-b border-border align-top transition-colors hover:bg-muted/50">
        <td className="px-4 py-3">
          <button type="button" className="btn btn-ghost btn-sm -ml-2 whitespace-nowrap font-medium"
            disabled={!item.permitted} aria-expanded={expanded} aria-controls={`mcp-tools-${item.id}`}
            onClick={() => { setExpanded(!expanded); }}>
            {expanded ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
            {item.name}
          </button>
        </td>
        <td className="px-4 py-3 text-muted-foreground">
          {personal ? "Personal" : item.authentication_model === "shared-authentication" ? "Company-managed" : "No provider sign-in"}
        </td>
        <td className="min-w-56 space-y-1 px-4 py-3" aria-live="polite">
          <p className={`text-sm ${!reason && summary.failed ? "text-error" : "text-foreground"}`}>{label}</p>
          {!reason && unavailableErrors.map((message) => <p key={message} className="max-w-sm text-xs text-muted-foreground">{message}</p>)}
          {accounts.map((account) => <p key={account} className="max-w-sm break-words text-sm">{account}</p>)}
          {checkedAt && <CheckedAt value={checkedAt} />}
          {personal && !reason && <p className="text-xs text-muted-foreground">
            {connection?.status === "refresh pending" ? "Connection refresh pending" : "Provider connected"}
          </p>}
          {personal && (connectionError || connection?.message) && <p role="alert" className="max-w-sm text-xs text-error">
            {connectionError || connection?.message}
          </p>}
        </td>
        <td className="px-4 py-3">
          <div className="flex flex-wrap items-start gap-2">
            {item.permitted && (!reason || statusUnavailable || pendingRefresh[item.id]) && <button type="button" className="btn btn-sm btn-outline"
              disabled={!!pendingRefresh[item.id] || checking && personal || !!state?.busy || now < retryUntil}
              onClick={() => { if (statusUnavailable) void onRefresh(item.id); else onRecheck(); }}>
              Recheck
            </button>}
            {personal && item.permitted && connectionsEnabled && <McpConnection id={item.id}
              status={connection?.status} onRefresh={() => void onRefresh(item.id)} />}
          </div>
          {personal && item.can_discover && <div className="mt-2"><McpDiscovery id={item.id}
            initial={item.publication} onRefresh={(marker) => onRefresh(item.id, marker)} /></div>}
          {!item.can_discover && item.permitted && item.publication?.state !== "published" && item.publication && (
            <p className="mt-2 text-xs text-muted-foreground">
              {item.publication.state === "error" ? "Publication failed" : item.publication.state === "unavailable"
                ? "Publication status unavailable" : "Tool discovery pending"}
            </p>
          )}
          {!item.permitted && <span className="text-xs text-muted-foreground">Ask an operator for access</span>}
        </td>
      </tr>
      <tr id={`mcp-tools-${item.id}`} hidden={!expanded} className="border-b border-border bg-muted/20">
        <td colSpan={4} className="px-4 py-4 sm:px-8">
          <h2 className="mb-3 text-sm font-medium">Approved tools</h2>
          {state?.message && <p className="mb-3 text-sm text-muted-foreground">{state.message}</p>}
          {state?.busy && !state.tools && <p role="status" className="text-sm text-muted-foreground">Loading tools…</p>}
          {state?.tools?.length === 0 && <p className="text-sm text-muted-foreground">No approved tools are currently available.</p>}
          {state?.tools && <table className="table w-full text-sm">
            <thead><tr><th>Tool</th><th>Description</th><th>Configured checks</th></tr></thead>
            <tbody>{state.tools.map((tool) => <tr key={tool.name} className="align-top">
              <td className="font-mono text-xs">{tool.name}</td>
              <td className="max-w-xl whitespace-pre-wrap break-words"><p className="line-clamp-3" title={tool.description}>{tool.description || "—"}</p></td>
              <td className="min-w-64">{Object.keys(tool.checks).length ? Object.entries(tool.checks).map(([id, check]) => (
                <ToolCheck key={id} check={check} value={state.checks[id]} busy={state.busy} />
              )) : <span className="text-xs text-muted-foreground">No check configured</span>}</td>
            </tr>)}</tbody>
          </table>}
        </td>
      </tr>
    </Fragment>
  );
}

function prettyResult(value: string): string {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) && !Object.keys(parsed).length) return "";
    return JSON.stringify(parsed, null, 2);
  } catch { return value; }
}

function ToolCheck({ check, value, busy }: { check: McpCheck; value?: CheckState; busy: boolean }) {
  const failed = value?.result?.status === "failed";
  const parameters = Object.keys(check.arguments).length > 0;
  const result = value?.result?.result ? prettyResult(value.result.result) : "";
  return (
    <div className="mb-3 space-y-2 last:mb-0">
      <div className="flex items-center justify-between gap-4 text-xs">
        <span className="font-medium">{check.name}</span>
        <span className={failed ? "text-error" : "text-muted-foreground"}>
          {failed ? "Failed" : value?.error ? "Unavailable" : value?.result ? "Passed" : value?.running ? "Checking…" : busy ? "Queued…" : "Not checked"}
        </span>
      </div>
      {value?.error && <p className="max-w-sm text-xs text-muted-foreground">{value.error}</p>}
      {(parameters || result) && <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">Details</summary>
        <div className="mt-2 space-y-3">
          {parameters && <div><p className="mb-1 font-medium">Fixed parameters</p><pre className="max-h-48 max-w-xl overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-card p-3 font-mono">{JSON.stringify(check.arguments, null, 2)}</pre></div>}
          {result && <div><p className="mb-1 font-medium">Result</p><pre className="max-h-64 max-w-xl overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-card p-3 font-mono">{result}</pre></div>}
        </div>
      </details>}
    </div>
  );
}
