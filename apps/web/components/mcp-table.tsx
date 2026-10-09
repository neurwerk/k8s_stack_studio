"use client";

import { Fragment, useState, useEffect } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { McpConnection } from "@/components/mcp-connection";
import { McpDiscovery } from "@/components/mcp-discovery";
import { fetchMcpTools, mcpError, runMcpCheck } from "@/lib/api/mcp";
import { ApiRequestError } from "@/lib/api/client";
import { McpChecks, checkSummary, skipReason, needsMcpMetadataRefresh } from "@/lib/mcp-checks";
import type { IntegrationChecks, CheckState } from "@/lib/mcp-checks";
import type { McpCatalogEntry, McpConnectionStatus, McpCheck } from "@/lib/api/mcp";

interface TableProps {
  showDiscovery?: boolean;
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
            {["MCP", "Authentication type", "Checks / account", "Actions"].map((title) => (
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
    <time dateTime={value} title={date.toLocaleString()} className="block text-xs font-normal leading-4 text-foreground">
      Checked {date.toLocaleString(undefined, {
        ...(today ? {} : { month: "short", day: "numeric", year: "numeric" }),
        hour: "2-digit", minute: "2-digit",
      })}
    </time>
  );
}

function McpRow({ item, connections, connectionsEnabled, checking, connectionError, connectionRetryUntil, statusRetryUntil, onRefresh, pendingRefresh, state, onRecheck, showDiscovery = true }:
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
  const configuredChecks = state?.tools?.reduce((count, tool) => count + Object.keys(tool.checks).length, 0) ?? 0;
  const allPassed = configuredChecks > 0 && !state?.busy && !state?.message &&
    Object.values(state?.checks ?? {}).filter((check) => check.result?.status === "passed").length === configuredChecks;
  const results = Object.values(state?.checks ?? {}).flatMap((check) => check.result ? [check.result] : []);
  const checkedAt = Object.values(state?.checks ?? {}).flatMap((check) => {
    const timestamp = check.result?.checked_at ?? check.checkedAt;
    return timestamp ? [timestamp] : [];
  }).sort().at(-1);
  const accounts = [...new Set(results.filter((result) => result.status === "passed" && result.display_value !== null)
    .map((result) => `${result.display_label ?? "Account"}: ${result.display_value ?? ""}`))];
  const label = checking && personal && !connection && !connectionError
    ? "Checking connection…" : reason || (allPassed ? "" : summary.label);
  const metadataUnavailable = needsMcpMetadataRefresh(item, connection, connectionsEnabled, connectionError);
  const unavailableErrors = [...new Set(Object.values(state?.checks ?? {}).flatMap((check) => check.error ? [check.error] : []))];

  return (
    <Fragment>
      <tr className="border-b border-border align-top text-xs font-normal leading-4 transition-colors hover:bg-muted/50">
        <td className="px-4 py-3 text-xs font-normal leading-4">
          <button type="button" className="inline-flex h-4 items-center gap-2 whitespace-nowrap text-xs font-medium leading-4 text-foreground hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!item.permitted} aria-expanded={expanded} aria-controls={`mcp-tools-${item.id}`}
            onClick={() => { setExpanded(!expanded); }}>
            {expanded ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
            {item.name}
          </button>
        </td>
        <td className="px-4 py-3 text-xs font-normal leading-4 text-foreground">
          {personal ? "Individual key" : "Shared key"}
        </td>
        <td className="min-w-56 space-y-1 px-4 py-3 text-xs font-normal leading-4 text-foreground" aria-live="polite">
          {label && <p className={!reason && summary.failed ? "text-error" : ""}>{label}</p>}
          {!reason && unavailableErrors.map((message) => <p key={message} className="max-w-sm">{message}</p>)}
          {checkedAt && <CheckedAt value={checkedAt} />}
          {accounts.map((account) => <p key={account} className="max-w-sm break-words">{account}</p>)}
          {personal && !reason && connection?.status === "refresh pending" &&
            <p>Connection refresh pending</p>}
          {personal && (connectionError || connection?.message) && <p role="alert" className="max-w-sm text-error">
            {connectionError || connection?.message}
          </p>}
        </td>
        <td className="px-4 py-3 text-xs font-normal leading-4">
          <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
            {item.permitted && (!reason || metadataUnavailable || pendingRefresh[item.id]) && <button type="button" className="link link-primary inline-flex h-4 items-center text-xs font-normal leading-4 disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
              disabled={!!pendingRefresh[item.id] || checking && personal || !!state?.busy || now < retryUntil}
              onClick={() => { if (metadataUnavailable) void onRefresh(item.id); else onRecheck(); }}>
              Recheck
            </button>}
            {personal && item.permitted && connectionsEnabled && <McpConnection id={item.id}
              appearance="link" status={connection?.status} onRefresh={() => void onRefresh(item.id)} />}
          </div>
          {personal && item.can_discover && showDiscovery && <div className="mt-2"><McpDiscovery id={item.id}
             initial={item.publication} onRefresh={(marker) => onRefresh(item.id, marker)} /></div>}
          {(!item.can_discover || !showDiscovery) && item.permitted && item.publication?.state !== "published" && item.publication && (
             <p className="mt-2 text-foreground">
              {item.publication.state === "error" ? "Publication failed" : item.publication.state === "unavailable"
                ? "Publication status unavailable" : "Tool discovery pending"}
            </p>
          )}
          {!item.permitted && <span>Ask an operator for access</span>}
        </td>
      </tr>
      <tr id={`mcp-tools-${item.id}`} hidden={!expanded} className="border-b border-border bg-muted/20 text-xs leading-4">
        <td colSpan={4} className="px-4 py-4 text-xs leading-4 sm:px-8">
          {state?.message && <p className="mb-3 text-muted-foreground">{state.message}</p>}
          {state?.busy && !state.tools && <p role="status" className="text-muted-foreground">Loading tools…</p>}
          {state?.tools?.length === 0 && <p className="text-muted-foreground">No approved tools are currently available.</p>}
          {state?.tools && <table className="table w-full text-sm">
            <thead><tr><th>Tool</th><th>Description</th><th>Configured checks</th></tr></thead>
            <tbody className="text-xs leading-4">{state.tools.map((tool) => <tr key={tool.name} className="align-top">
              <td className="break-all text-xs font-medium leading-4 text-foreground">{tool.name}</td>
              <td className="max-w-xl text-xs leading-4"><ToolDescription description={tool.description} /></td>
              <td className="min-w-64 text-xs leading-4">{Object.keys(tool.checks).length ? Object.entries(tool.checks).map(([id, check]) => (
                <ToolCheck key={id} check={check} value={state.checks[id]} busy={state.busy} />
              )) : <span>No check configured</span>}</td>
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
    return JSON.stringify(parsed, null, 2);
  } catch { return value; }
}

function ToolDescription({ description }: { description: string }) {
  const [expanded, setExpanded] = useState(false);
  const long = description.length > 160;
  return (
    <div className="space-y-1">
      <p className={`whitespace-pre-wrap break-words ${long && !expanded ? "line-clamp-3" : ""}`}>
        {description || "—"}
      </p>
      {long && <button type="button" className="link link-primary text-xs font-normal"
        aria-expanded={expanded} onClick={() => { setExpanded(!expanded); }}>
        {expanded ? "Show less" : "Show more"}
      </button>}
    </div>
  );
}

function ToolCheck({ check, value, busy }: { check: McpCheck; value?: CheckState; busy: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const failed = value?.result?.status === "failed";
  const result = value?.result?.result ? prettyResult(value.result.result) : "";
  const error = value?.error ?? (failed ? "Check failed." : null);
  const status = failed ? "Failed" : error ? "Unavailable" : value?.running ? "Checking…" : busy ? "Queued…" : "";
  return (
    <div className="mb-3 last:mb-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button type="button" aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "Show"} input and output for ${check.name}`}
          className="-ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 text-left hover:bg-muted hover:text-primary"
          onClick={() => { setExpanded(!expanded); }}>
          {check.name}
          {expanded ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
        </button>
        {status && <span className={`ml-auto ${error ? "text-error" : "text-foreground"}`}>
          {status}
        </span>}
      </div>
      {expanded && <div className="mt-2 space-y-2 pl-4">
        <div>
          <p className="mb-1 font-medium">Input</p>
          <pre className="max-h-48 max-w-xl overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-card p-2 font-mono">{JSON.stringify(check.arguments, null, 2)}</pre>
        </div>
        {error && <p role="alert" className="text-error">{error}</p>}
        <div>
          <p className="mb-1 font-medium">Output</p>
          <pre className="max-h-64 max-w-xl overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-card p-2 font-mono">{result.length ? result : "No output available."}</pre>
        </div>
      </div>}
    </div>
  );
}
