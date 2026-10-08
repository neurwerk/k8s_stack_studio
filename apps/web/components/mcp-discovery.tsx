"use client";

import { useEffect, useRef, useState } from "react";
import { ApiRequestError } from "@/lib/api/client";
import { discoverMcp, fetchMcpPublication, mcpError } from "@/lib/api/mcp";
import type { McpPublicationStatus } from "@/lib/api/mcp";

function wait(seconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Polling stopped", "AbortError"));
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, seconds * 1000);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

export function McpDiscovery({
  id, initial, onRefresh,
}: {
  id: string;
  initial?: McpPublicationStatus | null;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [status, setStatus] = useState<McpPublicationStatus | null>(null);
  const [previousInitial, setPreviousInitial] = useState(initial);
  const [error, setError] = useState("");
  const [discoveredAt, setDiscoveredAt] = useState<string | null>(null);
  const [retryUntil, setRetryUntil] = useState(0);
  const active = useRef(true);
  const operation = useRef<AbortController | null>(null);
  const refresh = useRef(onRefresh);
  const latestInitial = useRef(initial);
  // A coordinated Connect/catalog refresh supersedes local polling results.
  if (previousInitial !== initial) {
    setPreviousInitial(initial);
    setStatus(null);
    setError("");
  }
  useEffect(() => { refresh.current = onRefresh; }, [onRefresh]);
  useEffect(() => { latestInitial.current = initial; }, [initial]);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      operation.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (!retryUntil) return;
    const timer = window.setTimeout(() => {
      setRetryUntil(0);
    }, Math.max(0, retryUntil - Date.now()));
    return () => {
      window.clearTimeout(timer);
    };
  }, [retryUntil]);

  async function run(discover: boolean) {
    if (operation.current || Date.now() < retryUntil) return;
    const controller = new AbortController();
    // Re-read mutable cancellation state after awaits; do not narrow it across the loop.
    const stopped = () => !active.current || controller.signal.aborted;
    operation.current = controller;
    setBusy(true);
    setDiscovering(discover);
    setError("");
    let timeout: number | undefined;
    let refreshed = false;
    try {
      let marker = discoveredAt;
      if (discover) {
        const result = await discoverMcp(id);
        if (stopped()) return;
        marker = result.discovered_at;
        setDiscoveredAt(marker);
        setDiscovering(false);
        setStatus({ state: "pending-discovery", checked_at: null, error_code: null });
        // Native discovery already mutated tools: invalidate now, not after polling.
        await refresh.current();
        refreshed = true;
        if (stopped()) return;
      }
      // Only read status. The operator independently reruns the existing setup Job.
      timeout = window.setTimeout(() => {
        controller.abort();
      }, 120_000);
      while (!stopped()) {
        let delay = 5;
        const requestedInitial = latestInitial.current;
        try {
          const result = await fetchMcpPublication(id, controller.signal);
          if (stopped()) return;
          const fresh = !marker || (result.checked_at !== null &&
            Date.parse(result.checked_at) > Date.parse(marker));
          const current = requestedInitial === latestInitial.current;
          if (current && (fresh || result.state === "unavailable")) setStatus(result);
          if (current && fresh && (result.state === "published" || result.state === "error")) {
            // Publication can change the approved tool mapping again.
            await refresh.current();
            refreshed = true;
            break;
          }
        } catch (error) {
          if (stopped()) break;
          if (error instanceof ApiRequestError && error.status === 429) {
            delay = Math.max(5, error.retryAfter ?? 60);
            setRetryUntil(Date.now() + delay * 1000);
          } else if (requestedInitial === latestInitial.current) {
            setStatus({ state: "unavailable", checked_at: null, error_code: null });
            setError("Publication status is unavailable.");
            break;
          }
        }
        await wait(delay, controller.signal);
      }
    } catch (error) {
      if (!stopped()) {
        setStatus({ state: "unavailable", checked_at: null, error_code: null });
        setError(error instanceof ApiRequestError && error.status === 409
          ? "Discovery is already running for this integration." : mcpError(error));
        if (error instanceof ApiRequestError && error.status === 429)
          setRetryUntil(Date.now() + (error.retryAfter ?? 60) * 1000);
      }
    } finally {
      if (timeout !== undefined) window.clearTimeout(timeout);
      operation.current = null;
      if (active.current) {
        setBusy(false);
        setDiscovering(false);
        if (!refreshed) await refresh.current();
      }
    }
  }

  const publication = status ?? initial;
  const published = publication?.state === "published" && (!discoveredAt ||
    (publication.checked_at !== null && Date.parse(publication.checked_at) > Date.parse(discoveredAt)));
  return (
    <div className="space-y-2" aria-live="polite">
      <button type="button" className="btn btn-sm btn-outline" disabled={busy || !!retryUntil}
        onClick={() => void run(true)}>
        {busy ? discovering ? "Discovering…" : "Checking publication…" : "Discover tools"}
      </button>
      {publication && <p className="max-w-xs text-xs text-muted-foreground">
        {published ? "Tools published" :
          publication.state === "error" ? "Publication failed. Check the setup Job." :
          publication.state === "unavailable" ? "Publication status unavailable" :
          discoveredAt ? "Discovered; publication pending. Run the setup publication Job." :
          "Tool discovery pending"}
      </p>}
      {!busy && discoveredAt && !published && (
        <button type="button" className="btn btn-xs btn-ghost" disabled={!!retryUntil}
          onClick={() => void run(false)}>Check publication</button>
      )}
      {error && <p role="alert" className="max-w-xs text-xs text-error">{error}</p>}
    </div>
  );
}
