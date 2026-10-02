"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ChevronDown, ChevronUp } from "lucide-react";
import { fetchLlmActivity } from "@/lib/api/llm-activity";
import type { Activity, ActivityFilters, ActivityType } from "@/lib/api/llm-activity";
import { useVerifiedSession } from "@/lib/auth/session-context";

function pretty(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function formatTokens(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat("en-US").format(value);
}

function formatCost(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 6,
  }).format(value);
}

function statusFor(item: Activity): string {
  return item.type === "TOOL" ? item.status ?? "Not recorded" : item.level ?? "Not recorded";
}

function statusColor(status: string): string {
  if (status === "INFO") return "badge-info";
  if (status === "Error" || status === "ERROR" || status === "FATAL") return "badge-error";
  if (status === "WARNING") return "badge-warning";
  return "badge-ghost";
}

function roleColor(role: string): string {
  if (role === "user") return "badge-primary";
  if (role === "assistant") return "badge-secondary";
  if (role === "system") return "badge-neutral";
  if (role === "tool") return "badge-info";
  return "badge-outline";
}

function resultPreview(raw: string | null): string {
  if (!raw) return "Not recorded";
  let value: unknown = raw;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    // Plain-text results are displayed as recorded.
  }
  if (Array.isArray(value)) {
    const messages = value as unknown[];
    const response = messages.findLast((entry) =>
      typeof entry === "object" && entry !== null && "role" in entry && entry.role === "assistant");
    value = response ?? messages.at(-1) ?? value;
  }
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    value = record.content ?? record["content.0.text"] ?? value;
  }
  const text = pretty(value).replace(/\s+/g, " ").trim();
  return text.length > 180 ? `${text.slice(0, 180)}…` : text || "No content recorded";
}

function recordedContent(raw: string | null, label: string, full: boolean): React.ReactNode {
  if (raw === null || raw === "") {
    return <p className="text-sm text-muted-foreground">{label} was not recorded.</p>;
  }
  let value: unknown = raw;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    // Plain text is still shown in full.
  }
  if (full) {
    return <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--code-background)] p-3 font-mono text-xs leading-relaxed text-[var(--code-foreground)]">{pretty(value)}</pre>;
  }
  const messages = Array.isArray(value)
    ? value
    : typeof value === "object" && value !== null && "messages" in value &&
        Array.isArray(value.messages)
      ? value.messages
      : typeof value === "object" && value !== null && "role" in value
        ? [value]
        : null;
  return (
    <div className="space-y-3">
      {messages && messages.length > 0 && (
        <ol className="space-y-3">
          {messages.map((message: unknown, index: number) => {
            const item = typeof message === "object" && message !== null ? message as Record<string, unknown> : null;
            return (
              <li key={index} className="rounded-md border border-border bg-card p-3">
                <span className={`badge badge-sm mb-2 font-medium ${roleColor(typeof item?.role === "string" ? item.role : "")}`}>
                  {typeof item?.role === "string" ? item.role : `Message ${String(index + 1)}`}
                </span>
                <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--code-background)] p-3 font-mono text-xs leading-relaxed text-[var(--code-foreground)]">{pretty(item?.content ?? message)}</pre>
              </li>
            );
          })}
        </ol>
      )}
      {!(messages && messages.length > 0) && (
        <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--code-background)] p-3 font-mono text-xs leading-relaxed text-[var(--code-foreground)]">{pretty(value)}</pre>
      )}
    </div>
  );
}

export default function LlmActivityPage() {
  const session = useVerifiedSession();
  if (!session.llm_logs_available) {
    return <p className="p-6 text-sm text-muted-foreground">LLM activity is not enabled.</p>;
  }
  return <ActivityView key={session.subject} />;
}

function ActivityView() {
  const [query, setQuery] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [type, setType] = useState<ActivityType>("all");
  const [items, setItems] = useState<Activity[]>([]);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [fullPayloadRows, setFullPayloadRows] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestNumber = useRef(0);
  const sessionColors = useMemo(() => {
    const ids = [...new Set(items.map((item) => item.sessionId).filter((id): id is string => Boolean(id)))].sort();
    return new Map(ids.map((id, index) => [
      id, `hsl(${((232 + index * 137.508) % 360).toFixed(1)} 55% 32%)`,
    ]));
  }, [items]);

  const toggleRow = (id: string) => {
    setExpandedRows((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleFullPayload = (id: string) => {
    setFullPayloadRows((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const search = async (filters: ActivityFilters): Promise<void> => {
    const current = ++requestNumber.current;
    setLoading(true);
    setItems([]);
    setExpandedRows(new Set());
    setFullPayloadRows(new Set());
    setError(null);
    try {
      const result = await fetchLlmActivity(filters);
      if (requestNumber.current === current) setItems(result);
    } catch {
      if (requestNumber.current === current) setError("Unable to load activity. Please try again.");
    } finally {
      if (requestNumber.current === current) setLoading(false);
    }
  };

  useEffect(() => {
    const current = ++requestNumber.current;
    void fetchLlmActivity({ q: "" })
      .then((result) => {
        if (requestNumber.current === current) setItems(result);
      })
      .catch(() => {
        if (requestNumber.current === current) setError("Unable to load activity. Please try again.");
      })
      .finally(() => {
        if (requestNumber.current === current) setLoading(false);
      });
    return () => { requestNumber.current += 1; };
  }, []);

  return (
    <div className="mx-auto max-w-[1600px] p-4 sm:p-6">
      <div className="mb-6 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">LLM &amp; MCP logs</h1>
        <span className="text-sm text-muted-foreground">
          {loading ? "Loading…" : `${String(items.length)} ${items.length === 1 ? "entry" : "entries"}`}
        </span>
      </div>
      <p className="mb-4 text-sm text-muted-foreground">
        Your 10 most recent matching LLM exchanges and MCP calls. Result previews show recorded
        responses; matching session IDs share a text color. Expand a row for recorded details.
      </p>
      <form
        className="card mb-4 space-y-3 border border-border bg-card p-4 sm:p-6"
        onSubmit={(event) => {
          event.preventDefault();
          if (Boolean(start) !== Boolean(end)) {
            setError("Set both From and To, or leave both blank.");
            return;
          }
          try {
            const from = start ? new Date(start).toISOString() : undefined;
            const to = end ? new Date(end).toISOString() : undefined;
            if (from && to && Date.parse(from) >= Date.parse(to)) {
              setError("From must be before To.");
              return;
            }
            void search({ q: query.trim(), type, start: from, end: to });
          } catch {
            setError("Enter a valid time range.");
          }
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(16rem,2fr)_minmax(10rem,1fr)]">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Query
            <input className="input input-bordered w-full bg-base-100 text-sm" type="search"
              maxLength={200} placeholder="Model content or MCP query…" value={query}
              onChange={(event) => { setQuery(event.target.value); }} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Activity type
            <select className="select select-bordered w-full bg-base-100 text-sm" value={type}
              onChange={(event) => { setType(event.target.value as ActivityType); }}>
              <option value="all">All activity</option>
              <option value="llm">LLM</option>
              <option value="mcp">MCP</option>
            </select>
          </label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(14rem,18rem)_minmax(14rem,18rem)_auto]">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            From (local time)
            <input className="input input-bordered w-full bg-base-100 text-sm" type="datetime-local"
              value={start} onChange={(event) => { setStart(event.target.value); }} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            To (local time)
            <input className="input input-bordered w-full bg-base-100 text-sm" type="datetime-local"
              value={end} onChange={(event) => { setEnd(event.target.value); }} />
          </label>
          <button className="btn btn-primary w-fit self-end justify-self-start" type="submit" disabled={loading}>Search</button>
        </div>
        <p className="text-xs text-muted-foreground">Time range: up to 90 days. Blank dates search the last 90 days. Search matches model input/output and recorded MCP queries.</p>
      </form>

      {error && <p role="alert" className="alert alert-error mb-4 text-sm">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="table w-full min-w-[1280px] table-fixed text-left text-sm">
          <colgroup>
            <col className="w-48" />
            <col className="w-24" />
            <col className="w-44" />
            <col className="w-72" />
            <col className="w-24" />
            <col className="w-32" />
            <col />
          </colgroup>
          <thead className="border-b border-border bg-muted/50 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Timestamp (local time)</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Session ID</th>
              <th className="px-3 py-2">Model / server</th>
              <th className="px-3 py-2 text-right">Tokens</th>
              <th className="px-3 py-2 text-right">Cost (USD)</th>
              <th className="px-3 py-2">Result</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const expanded = expandedRows.has(item.id);
              const fullPayload = fullPayloadRows.has(item.id);
              const status = statusFor(item);
              const activityName = item.type === "TOOL"
                ? `${item.server ? `${item.server} - ` : ""}${item.tool}`
                : item.model ?? item.name ?? "LLM request";
              const preview = resultPreview(item.type === "TOOL" ? item.result : item.output);
              const isError = item.type === "TOOL"
                ? item.status === "Error"
                : item.level === "ERROR" || item.level === "FATAL";
              return (
                <Fragment key={`${item.type}-${item.id}`}>
                  <tr onClick={() => { toggleRow(item.id); }}
                    className={`cursor-pointer hover:bg-muted/50 ${expanded ? "bg-muted/30" : "border-b border-border"}`}>
                    <td className="whitespace-nowrap px-3 py-1.5 align-top font-mono text-xs text-muted-foreground" title={item.startTime}>
                      {new Date(item.startTime).toLocaleString()}
                    </td>
                    <td className="px-3 py-1.5 align-top text-xs">
                      <span className={`badge badge-sm font-medium ${item.type === "TOOL" ? "badge-secondary" : "badge-primary"}`}>
                        {item.type === "TOOL" ? "MCP" : "LLM"}
                      </span>
                    </td>
                    <td className="truncate px-3 py-1.5 align-top font-mono text-xs" title={item.sessionId ?? undefined}>
                      {item.sessionId ? (
                        <span className="font-semibold" style={{ color: sessionColors.get(item.sessionId) }}>
                          {item.sessionId.length > 16 ? `${item.sessionId.slice(0, 16)}…` : item.sessionId}
                        </span>
                      ) : <span className="text-muted-foreground">Not recorded</span>}
                    </td>
                    <td className="truncate px-3 py-1.5 align-top font-mono text-xs" title={activityName}>
                      {activityName}
                    </td>
                    <td className="px-3 py-1.5 text-right align-top font-mono text-xs tabular-nums">{formatTokens(item.tokens)}</td>
                    <td className="px-3 py-1.5 text-right align-top font-mono text-xs tabular-nums">{formatCost(item.costUsd)}</td>
                    <td className="px-3 py-1.5 align-top font-mono text-xs">
                      <button type="button" aria-expanded={expanded}
                        aria-label={`${expanded ? "Hide" : "Show"} details for ${activityName}`}
                        onClick={(event) => { event.stopPropagation(); toggleRow(item.id); }}
                        className="flex w-full items-center gap-2 rounded text-left text-foreground hover:text-primary">
                        {isError && <span className="badge badge-error badge-sm shrink-0 font-medium">Error</span>}
                        <span className="min-w-0 flex-1 truncate" title={preview}>{preview}</span>
                        {expanded ? <ChevronUp className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          : <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
                      </button>
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="border-b border-border bg-muted/20">
                      <td colSpan={7} className="p-3">
                        <div className="rounded-md border border-border bg-background p-4">
                          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                            <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 xl:grid-cols-3">
                              <div><span className="font-medium text-foreground">Timestamp:</span> {item.startTime}</div>
                              <div className="break-all"><span className="font-medium text-foreground">{item.type === "TOOL" ? "Tool:" : "Model:"}</span> {item.type === "TOOL" ? item.tool : item.model ?? "—"}</div>
                              <div className="break-all"><span className="font-medium text-foreground">Session ID:</span>{" "}
                                {item.sessionId ? <span className="font-mono font-semibold" style={{ color: sessionColors.get(item.sessionId) }}>{item.sessionId}</span> : "Not recorded"}
                              </div>
                              <div><span className="font-medium text-foreground">Request time:</span>{" "}
                                {item.durationMs === null ? "Not recorded" : `${String(item.durationMs)} ms`}
                              </div>
                              {item.type === "TOOL" && item.status && item.status !== "Completed" && (
                                <div><span className="font-medium text-foreground">Outcome:</span>{" "}
                                  <span className={`badge badge-sm font-medium ${statusColor(status)}`}>{status}</span>
                                </div>
                              )}
                            </div>
                            <button type="button" aria-pressed={fullPayload}
                              onClick={() => { toggleFullPayload(item.id); }}
                              className="btn btn-outline btn-xs">
                              {fullPayload ? "Message view" : "Recorded payload"}
                            </button>
                          </div>
                          {fullPayload && (
                            <p className="mb-3 text-xs text-muted-foreground">
                              This is the observation recorded by Langfuse, not the original HTTP wire request.
                            </p>
                          )}
                          <div className="min-w-0">
                            <section className="min-w-0 rounded-lg border border-border bg-card p-4" aria-label={item.type === "TOOL" ? "Tool parameters" : "Sent to the model"}>
                              <h2 className="mb-3 text-sm font-semibold">{item.type === "TOOL" ? "Parameters sent to tool" : "Sent to model"}</h2>
                              {recordedContent(item.type === "TOOL" ? item.parameters : item.input,
                                item.type === "TOOL" ? "Parameters" : "Input", fullPayload)}
                            </section>
                            <div className="flex items-center gap-3 py-2 text-primary" aria-hidden="true">
                              <span className="h-px flex-1 bg-border" />
                              <span className="flex h-8 w-8 items-center justify-center rounded-full border border-primary/30 bg-accent">
                                <ArrowDown className="h-4 w-4" />
                              </span>
                              <span className="h-px flex-1 bg-border" />
                            </div>
                            <section className="min-w-0 rounded-lg border border-border bg-card p-4" aria-label={item.type === "TOOL" ? "Tool result" : "Received from the model"}>
                              <h2 className="mb-3 text-sm font-semibold">{item.type === "TOOL" ? "Result from tool" : "Received from model"}</h2>
                              {recordedContent(item.type === "TOOL" ? item.result : item.output,
                                item.type === "TOOL" ? "Result" : "Output", fullPayload)}
                            </section>
                          </div>
                          <section aria-label="Recorded metadata" className="mt-4 min-w-0 rounded-lg border border-border bg-card p-4">
                            <h2 className="text-sm font-semibold">Selected observation metadata</h2>
                            <p className="mb-3 mt-1 text-xs text-muted-foreground">
                              Context for the whole log entry, including recorded HTTP details.
                            </p>
                            {Object.keys(item.metadata).length === 0 ? (
                              <p className="text-sm text-muted-foreground">No metadata recorded.</p>
                            ) : fullPayload ? (
                              <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--code-background)] p-3 font-mono text-xs leading-relaxed text-[var(--code-foreground)]">{JSON.stringify(item.metadata, null, 2)}</pre>
                            ) : (
                              <dl className="max-h-[24rem] overflow-auto rounded-md border border-border bg-base-100 text-xs">
                                {Object.entries(item.metadata).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => (
                                  <div key={key} className="grid gap-1 border-b border-border/70 px-3 py-2 last:border-b-0 sm:grid-cols-[minmax(12rem,1fr)_minmax(0,2fr)] sm:gap-3">
                                    <dt className="break-all font-mono text-muted-foreground">{key}</dt>
                                    <dd className="min-w-0 whitespace-pre-wrap break-words font-mono text-foreground">{pretty(value)}</dd>
                                  </div>
                                ))}
                              </dl>
                            )}
                          </section>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                {error ? "Activity could not be loaded." : "No recorded activity matches these filters."}
              </td></tr>
            )}
            {loading && <tr><td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">Loading activity…</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
