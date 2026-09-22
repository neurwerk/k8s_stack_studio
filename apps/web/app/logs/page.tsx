"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronDown, ChevronUp } from "lucide-react";
import { FAILURE_TYPES, LOG_LEVELS, fetchLogs } from "@/lib/api/logs";
import { useIsOpensearchAdmin } from "@/lib/auth/roles";
import type { FailureType, LogEntry, LogLevel, LogsFilter } from "@/lib/api/logs";

const LEVEL_COLORS: Record<LogLevel, string> = {
  TRACE: "bg-muted text-muted-foreground",
  DEBUG: "bg-muted text-muted-foreground",
  INFO: "bg-blue-500/15 text-blue-500",
  WARNING: "bg-amber-500/15 text-amber-500",
  ERROR: "bg-red-500/15 text-red-500",
  FATAL: "bg-red-700 text-white",
  UNKNOWN: "border border-border text-muted-foreground",
};

function localTime(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString().slice(0, -1);
}

function timestamp(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) {
    throw new Error("Use timestamps with a timezone for start and end.");
  }
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error("Invalid log time range.");
  const day = Number(value.slice(8, 10));
  const month = Number(value.slice(5, 7));
  const year = Number(value.slice(0, 4));
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (year < 1 || day < 1 || day > days || Number(value.slice(11, 13)) > 23) {
    throw new Error("Invalid log date.");
  }
  return date.toISOString();
}

function readFilters(params: URLSearchParams): { filter: LogsFilter; error: string | null } {
  const filter: LogsFilter = {
    q: params.get("q") || undefined,
    namespace: params.get("namespace") || undefined,
    pod: params.get("pod") || undefined,
    size: 100,
  };
  try {
    if (params.has("start") || params.has("end")) {
      filter.start = timestamp(params.get("start") ?? "");
      filter.end = timestamp(params.get("end") ?? "");
    } else if (params.has("at")) {
      const raw = params.get("at") ?? "";
      const at = Number(raw);
      if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw) || !Number.isFinite(at)) {
        throw new Error("Invalid alert timestamp.");
      }
      filter.start = timestamp(new Date((at - 600) * 1000).toISOString());
      filter.end = timestamp(new Date((at + 300) * 1000).toISOString());
    }
    if (filter.start && filter.end && Date.parse(filter.start) >= Date.parse(filter.end)) {
      throw new Error("From must be before To.");
    }
    const level = params.get("level");
    const failureType = params.get("failure_type");
    let invalidFilter = false;
    if (level === null || LOG_LEVELS.some((value) => value === level)) {
      filter.level = (level ?? undefined) as LogLevel | undefined;
    } else {
      invalidFilter = true;
    }
    if (failureType === null || Object.hasOwn(FAILURE_TYPES, failureType)) {
      filter.failure_type = (failureType ?? undefined) as FailureType | undefined;
    } else {
      invalidFilter = true;
    }
    if (invalidFilter) {
      return { filter, error: "Invalid log filter link. Choose a valid log level and failure type." };
    }
    return { filter, error: null };
  } catch {
    return { filter, error: "Invalid time link. Set both From and To to a valid, ascending range." };
  }
}

export default function LogsPage() {
  return <Suspense fallback={<div className="p-6">Loading…</div>}><LogsRoute /></Suspense>;
}

function LogsRoute() {
  const params = useSearchParams();
  return <LogsView key={params.toString()} queryString={params.toString()} />;
}

function LogsView({ queryString }: { queryString: string }) {
  const router = useRouter();
  const [initial] = useState(() => readFilters(new URLSearchParams(queryString)));
  const isOpensearchAdmin = useIsOpensearchAdmin();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(initial.error);
  const [q, setQ] = useState(initial.filter.q ?? "");
  const [namespace, setNamespace] = useState(initial.filter.namespace ?? "");
  const [pod, setPod] = useState(initial.filter.pod ?? "");
  const [start, setStart] = useState(localTime(initial.filter.start));
  const [end, setEnd] = useState(localTime(initial.filter.end));
  const [level, setLevel] = useState<LogLevel | "">(initial.filter.level ?? "");
  const [failureType, setFailureType] = useState<FailureType | "">(initial.filter.failure_type ?? "");
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const toggleRow = (i: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(i)) {
        next.delete(i);
      } else {
        next.add(i);
      }
      return next;
    });
  };

  const load = useCallback((filter: LogsFilter) => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchLogs(filter)
      .then((data) => {
        if (!cancelled) {
          setEntries(data.hits);
          setTotal(data.total);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Validate URL bounds before any authorized search.
  useEffect(() => {
    if (isOpensearchAdmin && !initial.error) return load(initial.filter);
    setLoading(false);
  }, [isOpensearchAdmin, initial, load]);

  const search = () => {
    try {
      if (Boolean(start) !== Boolean(end) || (initial.error?.startsWith("Invalid time") && (!start || !end))) {
        throw new Error("Set both From and To.");
      }
      const filter: LogsFilter = { q: q || undefined, namespace: namespace || undefined, pod: pod || undefined, size: 100 };
      filter.level = level || undefined;
      filter.failure_type = failureType || undefined;
      if (start && end) {
        // Keep the exact linked instant across daylight-saving clock changes.
        filter.start = start === localTime(initial.filter.start) ? initial.filter.start : new Date(start).toISOString();
        filter.end = end === localTime(initial.filter.end) ? initial.filter.end : new Date(end).toISOString();
        if (!filter.start || !filter.end || Date.parse(filter.start) >= Date.parse(filter.end)) {
          throw new Error("From must be before To.");
        }
      }
      const params = new URLSearchParams();
      for (const key of ["namespace", "pod", "q", "start", "end", "level", "failure_type"] as const) {
        const value = filter[key];
        if (value) params.set(key, value);
      }
      if (params.toString() === queryString) load(filter);
      else router.replace(`/logs${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid log time range.");
    }
  };

  if (!isOpensearchAdmin) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
          <p className="font-semibold">Access Denied</p>
          <p className="mt-1">
            You need the{" "}
            <code className="rounded bg-red-100 px-1">opensearch-admin</code>{" "}
            role to view logs.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Logs</h1>
        <span className="text-sm text-muted-foreground">
          {loading ? "Loading…" : `${entries.length} of ${total} entries`}
        </span>
      </div>

      <p className="mb-4 text-sm text-muted-foreground">
        Log level comes from the application; failure type comes from monitoring classification.
        Older logs may show UNKNOWN and Unclassified.
      </p>
      {/* Filter bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          search();
        }}
        className="mb-4 flex flex-wrap items-center gap-2"
      >
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Log level
          <select value={level} onChange={(e) => { setLevel(e.target.value as LogLevel | ""); }}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground">
            <option value="">All levels</option>
            {LOG_LEVELS.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Failure type
          <select value={failureType} onChange={(e) => { setFailureType(e.target.value as FailureType | ""); }}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground">
            <option value="">All types</option>
            {Object.entries(FAILURE_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <input
          type="text"
          aria-label="Query"
          placeholder="Query (e.g. error AND timeout)…"
          value={q}
          onChange={(e) => { setQ(e.target.value); }}
          className="w-72 rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <input
          type="text"
          placeholder="Namespace…"
          aria-label="Namespace"
          value={namespace}
          onChange={(e) => { setNamespace(e.target.value); }}
          className="w-44 rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <input
          type="text"
          placeholder="Pod…"
          aria-label="Pod"
          value={pod}
          onChange={(e) => { setPod(e.target.value); }}
          className="w-44 rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          From (local time)
          <input type="datetime-local" step="0.001" value={start} onChange={(e) => { setStart(e.target.value); }}
            className="max-w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          To (local time)
          <input type="datetime-local" step="0.001" value={end} onChange={(e) => { setEnd(e.target.value); }}
            className="max-w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground" />
        </label>
        <button
          type="submit"
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Search
        </button>
      </form>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Log table */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-muted/50 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="whitespace-nowrap px-3 py-2">Timestamp</th>
              <th className="whitespace-nowrap px-3 py-2">Log level</th>
              <th className="whitespace-nowrap px-3 py-2">Failure type</th>
              <th className="px-3 py-2">Namespace</th>
              <th className="px-3 py-2">Pod</th>
              <th className="px-3 py-2">Log</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, i) => {
              const expanded = expandedRows.has(i);
              const entryLevel = entry.level ?? "UNKNOWN";
              return (
                <tr key={i} className="border-b border-border last:border-0">
                  <td className="whitespace-nowrap px-3 py-1.5 align-top font-mono text-xs text-muted-foreground">
                    {entry.timestamp}
                  </td>
                  <td className="px-3 py-1.5 align-top text-xs">
                    <span className={`inline-block rounded px-2 py-0.5 font-medium ${LEVEL_COLORS[entryLevel]}`}>{entryLevel}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 align-top text-xs">
                    <span className="inline-block rounded bg-muted px-2 py-0.5 text-muted-foreground">
                      {entry.failure_type ? FAILURE_TYPES[entry.failure_type] : "Unclassified"}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 align-top text-xs">
                    {entry.namespace}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 align-top font-mono text-xs">
                    {entry.pod}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-xs">
                    <div className="flex items-start gap-1">
                      <span
                        className={
                          expanded
                            ? "whitespace-pre-wrap break-all"
                            : "line-clamp-2 break-all"
                        }
                      >
                        {entry.log}
                      </span>
                      <button
                        onClick={() => { toggleRow(i); }}
                        className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                        aria-label={expanded ? "Collapse log" : "Expand log"}
                        title={expanded ? "Show less" : "Show full log"}
                      >
                        {expanded ? (
                          <ChevronUp className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!loading && entries.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-6 text-center text-muted-foreground"
                >
                  No log entries found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
