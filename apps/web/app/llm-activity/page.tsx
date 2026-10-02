"use client";

import { useEffect, useRef, useState } from "react";
import { fetchLlmActivity } from "@/lib/api/llm-activity";
import type { ActivityFilters, LlmExchange } from "@/lib/api/llm-activity";
import { useVerifiedSession } from "@/lib/auth/session-context";

function pretty(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function recordedContent(raw: string | null, label: string): React.ReactNode {
  if (raw === null || raw === "") {
    return <p className="text-sm text-muted-foreground">{label} was not recorded.</p>;
  }
  let value: unknown = raw;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    // Plain text is still shown in full.
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
              <li key={index} className="rounded-md border border-border bg-base-100 p-3">
                <span className="badge badge-outline mb-2 text-xs">
                  {typeof item?.role === "string" ? item.role : `Message ${String(index + 1)}`}
                </span>
                <pre className="whitespace-pre-wrap break-words font-mono text-xs">{pretty(item?.content ?? message)}</pre>
              </li>
            );
          })}
        </ol>
      )}
      {messages && messages.length > 0 ? (
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground">Full recorded {label.toLowerCase()} payload</summary>
          <pre className="mt-2 max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-neutral p-3 font-mono text-xs text-neutral-content">{pretty(value)}</pre>
        </details>
      ) : (
        <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-md bg-neutral p-3 font-mono text-xs text-neutral-content">{pretty(value)}</pre>
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
  const [items, setItems] = useState<LlmExchange[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestNumber = useRef(0);

  const search = async (filters: ActivityFilters): Promise<void> => {
    const current = ++requestNumber.current;
    setLoading(true);
    setItems([]);
    setError(null);
    try {
      const result = await fetchLlmActivity(filters);
      if (requestNumber.current === current) setItems(result);
    } catch {
      if (requestNumber.current === current) setError("Unable to load LLM activity. Please try again.");
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
        if (requestNumber.current === current) setError("Unable to load LLM activity. Please try again.");
      })
      .finally(() => {
        if (requestNumber.current === current) setLoading(false);
      });
    return () => { requestNumber.current += 1; };
  }, []);

  return (
    <div className="mx-auto max-w-[1600px] p-4 sm:p-6">
      <h1 className="text-2xl font-semibold tracking-tight">My LLM activity</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Your 10 most recent matching exchanges. Only content recorded by tracing is available.
      </p>
      <form
        className="card my-4 space-y-3 border border-border bg-card p-4 sm:p-6"
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
            void search({ q: query.trim(), start: from, end: to });
          } catch {
            setError("Enter a valid time range.");
          }
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(14rem,2fr)_minmax(12rem,1fr)_minmax(12rem,1fr)_auto]">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Query
            <input className="input input-bordered w-full bg-base-100 text-sm" type="search"
              maxLength={200} placeholder="Words in a request or response…" value={query}
              onChange={(event) => { setQuery(event.target.value); }} />
          </label>
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
          <button className="btn btn-primary w-fit self-end" type="submit" disabled={loading}>Search</button>
        </div>
        <p className="text-xs text-muted-foreground">Time range: up to 90 days. Blank dates search the last 90 days. Search matches whole words or phrases.</p>
      </form>

      {error && <p role="alert" className="alert alert-error my-4 text-sm">{error}</p>}
      {loading ? (
        <p role="status" className="py-8 text-sm text-muted-foreground">Loading activity…</p>
      ) : items.length === 0 && !error ? (
        <p className="py-8 text-sm text-muted-foreground">No recorded exchanges match these filters.</p>
      ) : (
        <ol className="space-y-3">
          {items.map((item) => (
            <li key={item.id}>
              <details className="card min-w-0 border border-border bg-card p-4 sm:p-5">
                <summary className="cursor-pointer text-sm font-medium">
                  <span className="mr-2">{new Date(item.startTime).toLocaleString()}</span>
                  <span className="break-all text-muted-foreground">{item.model ?? item.name ?? "LLM request"}</span>
                  {item.level && item.level !== "DEFAULT" && <span className="badge badge-warning ml-2">{item.level}</span>}
                </summary>
                <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
                  <section className="min-w-0" aria-label="Sent to the model">
                    <h2 className="mb-2 font-semibold">Sent</h2>
                    {recordedContent(item.input, "Input")}
                  </section>
                  <section className="min-w-0" aria-label="Received from the model">
                    <h2 className="mb-2 font-semibold">Received</h2>
                    {recordedContent(item.output, "Output")}
                  </section>
                </div>
              </details>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
