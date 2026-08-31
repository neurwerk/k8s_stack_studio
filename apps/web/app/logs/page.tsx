"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { fetchLogs } from "@/lib/api/logs";
import { useIsOpensearchAdmin } from "@/lib/auth/roles";
import type { LogEntry } from "@/lib/api/logs";

export default function LogsPage() {
  const isOpensearchAdmin = useIsOpensearchAdmin();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [namespace, setNamespace] = useState("");
  const [pod, setPod] = useState("");
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

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchLogs({
      q: q || undefined,
      namespace: namespace || undefined,
      pod: pod || undefined,
      size: 100,
    })
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
  }, [q, namespace, pod]);

  // Initial load (last 100 logs, unfiltered) — only once the role is known
  useEffect(() => {
    if (isOpensearchAdmin) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpensearchAdmin]);

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

      {/* Filter bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          load();
        }}
        className="mb-4 flex flex-wrap items-center gap-2"
      >
        <input
          type="text"
          placeholder="Query (e.g. error AND timeout)…"
          value={q}
          onChange={(e) => { setQ(e.target.value); }}
          className="w-72 rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <input
          type="text"
          placeholder="Namespace…"
          value={namespace}
          onChange={(e) => { setNamespace(e.target.value); }}
          className="w-44 rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <input
          type="text"
          placeholder="Pod…"
          value={pod}
          onChange={(e) => { setPod(e.target.value); }}
          className="w-44 rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
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
              <th className="px-3 py-2">Namespace</th>
              <th className="px-3 py-2">Pod</th>
              <th className="px-3 py-2">Log</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, i) => {
              const expanded = expandedRows.has(i);
              return (
                <tr key={i} className="border-b border-border last:border-0">
                  <td className="whitespace-nowrap px-3 py-1.5 align-top font-mono text-xs text-muted-foreground">
                    {entry.timestamp}
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
                  colSpan={4}
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
