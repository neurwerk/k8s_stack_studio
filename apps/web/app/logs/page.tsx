"use client";

import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, ChevronDown, ChevronUp, Copy } from "lucide-react";
import { FAILURE_TYPES, LOG_LEVELS, fetchLogs } from "@/lib/api/logs";
import { useIsOpensearchAdmin } from "@/lib/auth/roles";
import type { FailureType, LogEntry, LogLevel, LogsFilter } from "@/lib/api/logs";

const PAGE_SIZE = 100;
const MAX_RESULTS = 10_000;

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
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, -1);
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

function formatLog(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function formatLogTimestamp(value: string, formatter: Intl.DateTimeFormat | null): string {
  if (!formatter) return value;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? formatter.format(date) : value;
}

function readFilters(params: URLSearchParams): { filter: LogsFilter; error: string | null } {
  const pageValue = params.get("page");
  const page = pageValue === null ? 1 : Number(pageValue);
  const offset = (page - 1) * PAGE_SIZE;
  const filter: LogsFilter = {
    q: params.get("q") || undefined,
    namespace: params.get("namespace") || undefined,
    pod: params.get("pod") || undefined,
    size: PAGE_SIZE,
    offset,
  };
  if (!Number.isSafeInteger(page) || page < 1 || offset >= MAX_RESULTS) {
    return { filter, error: "Invalid log page. Choose a page from 1 to 100." };
  }
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
      return {
        filter,
        error: "Invalid log filter link. Choose a valid log level and failure type.",
      };
    }
    return { filter, error: null };
  } catch {
    return {
      filter,
      error: "Invalid time link. Set both From and To to a valid, ascending range.",
    };
  }
}

export default function LogsPage() {
  return (
    <Suspense fallback={<div className="p-6">Loading…</div>}>
      <LogsRoute />
    </Suspense>
  );
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
  const [failureType, setFailureType] = useState<FailureType | "">(
    initial.filter.failure_type ?? "",
  );
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const [copiedRow, setCopiedRow] = useState<number | null>(null);
  const [timeZone, setTimeZone] = useState<string | null>(null);
  useEffect(() => {
    setTimeZone(Intl.DateTimeFormat().resolvedOptions().timeZone);
  }, []);
  const logTimeFormatter = useMemo(
    () => timeZone ? new Intl.DateTimeFormat("sv-SE", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }) : null,
    [timeZone],
  );
  const page = Math.floor((initial.filter.offset ?? 0) / PAGE_SIZE) + 1;
  const lastVisibleEntry = Math.min(page * PAGE_SIZE, total);
  const canGoNext = lastVisibleEntry < Math.min(total, MAX_RESULTS);

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
    return () => {
      cancelled = true;
    };
  }, []);

  // Validate URL bounds before any authorized search.
  useEffect(() => {
    if (isOpensearchAdmin && !initial.error) return load(initial.filter);
    setLoading(false);
  }, [isOpensearchAdmin, initial, load]);

  const search = () => {
    try {
      if (
        Boolean(start) !== Boolean(end) ||
        (initial.error?.startsWith("Invalid time") && (!start || !end))
      ) {
        throw new Error("Set both From and To.");
      }
      const filter: LogsFilter = {
        q: q || undefined,
        namespace: namespace || undefined,
        pod: pod || undefined,
        size: PAGE_SIZE,
      };
      filter.level = level || undefined;
      filter.failure_type = failureType || undefined;
      if (start && end) {
        // Keep the exact linked instant across daylight-saving clock changes.
        filter.start =
          start === localTime(initial.filter.start)
            ? initial.filter.start
            : new Date(start).toISOString();
        filter.end =
          end === localTime(initial.filter.end) ? initial.filter.end : new Date(end).toISOString();
        if (!filter.start || !filter.end || Date.parse(filter.start) >= Date.parse(filter.end)) {
          throw new Error("From must be before To.");
        }
      }
      const params = new URLSearchParams();
      for (const key of [
        "namespace",
        "pod",
        "q",
        "start",
        "end",
        "level",
        "failure_type",
      ] as const) {
        const value = filter[key];
        if (value) params.set(key, value);
      }
      if (params.toString() === queryString) load(filter);
      else router.replace(`/logs${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid log time range.");
    }
  };

  const goToPage = (nextPage: number) => {
    const nextParams = new URLSearchParams(queryString);
    if (nextPage === 1) nextParams.delete("page");
    else nextParams.set("page", String(nextPage));
    router.replace(`/logs${nextParams.size ? `?${nextParams.toString()}` : ""}`, {
      scroll: false,
    });
  };

  if (!isOpensearchAdmin) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
          <p className="font-semibold">Access Denied</p>
          <p className="mt-1">
            You need the <code className="rounded bg-red-100 px-1">opensearch-admin</code> role to
            view logs.
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
          {loading
            ? "Loading…"
            : total === 0
              ? "0 entries"
              : `${(page - 1) * PAGE_SIZE + 1}-${lastVisibleEntry} of ${total} entries`}
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
        className="mb-4 space-y-3"
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[minmax(16rem,2fr)_minmax(10rem,1fr)_minmax(10rem,1fr)_minmax(9rem,1fr)_minmax(11rem,1fr)]">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Query
            <input
              type="text"
              placeholder="e.g. error AND timeout…"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
              }}
              className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Namespace
            <input
              type="text"
              placeholder="Namespace…"
              value={namespace}
              onChange={(e) => {
                setNamespace(e.target.value);
              }}
              className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Pod
            <input
              type="text"
              placeholder="Pod…"
              value={pod}
              onChange={(e) => {
                setPod(e.target.value);
              }}
              className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Log level
            <select
              value={level}
              onChange={(e) => {
                setLevel(e.target.value as LogLevel | "");
              }}
              className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground"
            >
              <option value="">All levels</option>
              {LOG_LEVELS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Failure type
            <select
              value={failureType}
              onChange={(e) => {
                setFailureType(e.target.value as FailureType | "");
              }}
              className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground"
            >
              <option value="">All types</option>
              {Object.entries(FAILURE_TYPES).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(14rem,18rem)_minmax(14rem,18rem)_auto]">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            From (local time)
            <input
              type="datetime-local"
              step="0.001"
              value={start}
              onChange={(e) => {
                setStart(e.target.value);
              }}
              className="h-9 max-w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            To (local time)
            <input
              type="datetime-local"
              step="0.001"
              value={end}
              onChange={(e) => {
                setEnd(e.target.value);
              }}
              className="h-9 max-w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
            />
          </label>
          <button
            type="submit"
            className="h-9 w-fit self-end justify-self-start rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Search
          </button>
        </div>
      </form>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Log table */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[1000px] table-fixed text-left text-sm">
          <colgroup>
            <col className="w-48" />
            <col className="w-28" />
            <col className="w-40" />
            <col className="w-40" />
            <col className="w-56" />
            <col />
          </colgroup>
          <thead className="border-b border-border bg-muted/50 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2">
                <span className="block">Timestamp</span>
                {timeZone && (
                  <span className="block truncate font-normal normal-case" title={timeZone}>
                    {timeZone}
                  </span>
                )}
              </th>
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
                <Fragment key={`${entry.index}-${entry.timestamp}-${i}`}>
                  <tr className={expanded ? "bg-muted/30" : "border-b border-border"}>
                    <td className="whitespace-nowrap px-3 py-1.5 align-top font-mono text-xs text-muted-foreground" title={entry.timestamp}>
                      {formatLogTimestamp(entry.timestamp, logTimeFormatter)}
                    </td>
                    <td className="px-3 py-1.5 align-top text-xs">
                      <span
                        className={`inline-block rounded px-2 py-0.5 font-medium ${LEVEL_COLORS[entryLevel]}`}
                      >
                        {entryLevel}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 align-top text-xs">
                      <span className="inline-block rounded bg-muted px-2 py-0.5 text-muted-foreground">
                        {entry.failure_type ? FAILURE_TYPES[entry.failure_type] : "Unclassified"}
                      </span>
                    </td>
                    <td className="truncate px-3 py-1.5 align-top text-xs" title={entry.namespace}>
                      {entry.namespace || "—"}
                    </td>
                    <td
                      className="truncate px-3 py-1.5 align-top font-mono text-xs"
                      title={entry.pod}
                    >
                      {entry.pod || "—"}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-xs">
                      <button
                        type="button"
                        onClick={() => {
                          toggleRow(i);
                        }}
                        className="flex w-full items-center gap-2 rounded text-left text-muted-foreground hover:text-foreground"
                        aria-expanded={expanded}
                      >
                        <span className="min-w-0 flex-1 truncate text-foreground">{entry.log}</span>
                        {expanded ? (
                          <ChevronUp className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        )}
                      </button>
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="border-b border-border bg-muted/20">
                      <td colSpan={6} className="p-3">
                        <div className="rounded-md border border-border bg-background p-4">
                          <div className="mb-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 xl:grid-cols-4">
                            <div>
                              <span className="font-medium text-foreground">Timestamp:</span>{" "}
                              {entry.timestamp}
                            </div>
                            <div className="break-all">
                              <span className="font-medium text-foreground">Namespace:</span>{" "}
                              {entry.namespace || "—"}
                            </div>
                            <div className="break-all">
                              <span className="font-medium text-foreground">Pod:</span>{" "}
                              {entry.pod || "—"}
                            </div>
                            <div className="break-all">
                              <span className="font-medium text-foreground">Container:</span>{" "}
                              {entry.container || "—"}
                            </div>
                          </div>
                          <div className="mb-2 flex items-center justify-between gap-3">
                            <span className="text-xs font-medium text-muted-foreground">
                              Full log
                            </span>
                            <button
                              type="button"
                              onClick={() => {
                                void navigator.clipboard
                                  .writeText(entry.log)
                                  .then(() => {
                                    setCopiedRow(i);
                                  })
                                  .catch(() => {
                                    setCopiedRow(null);
                                  });
                              }}
                              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
                            >
                              {copiedRow === i ? (
                                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                              ) : (
                                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                              )}
                              {copiedRow === i ? "Copied" : "Copy original log"}
                            </button>
                          </div>
                          <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-3 font-mono text-xs leading-relaxed text-foreground">
                            {formatLog(entry.log)}
                          </pre>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {!loading && entries.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                  No log entries found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => {
            goToPage(page - 1);
          }}
          disabled={loading || page === 1}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          Previous
        </button>
        <span className="text-sm text-muted-foreground">Page {page}</span>
        <button
          type="button"
          onClick={() => {
            goToPage(page + 1);
          }}
          disabled={loading || !canGoNext}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}
