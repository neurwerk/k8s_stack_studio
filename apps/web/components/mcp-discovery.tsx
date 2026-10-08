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
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [status, setStatus] = useState<McpPublicationStatus | null>(null);
  const [error, setError] = useState("");
  const [discoveredAt, setDiscoveredAt] = useState<string | null>(null);
  const [retryUntil, setRetryUntil] = useState(0);
  const active = useRef(true);
  const operation = useRef<AbortController | null>(null);
  const refresh = useRef(onRefresh);
  useEffect(() => { refresh.current = onRefresh; }, [onRefresh]);
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
    const stopped = () => controller.signal.aborted;
    operation.current = controller;
    setBusy(true);
    setDiscovering(discover);
    setError("");
    let timeout: number | undefined;
    try {
      let marker = discoveredAt;
      if (discover) {
        const result = await discoverMcp(id);
        if (!active.current || stopped()) return;
        marker = result.discovered_at;
        setDiscoveredAt(marker);
        setDiscovering(false);
        setStatus({ state: "pending-discovery", checked_at: null, error_code: null });
      }
      // Only read status. The operator independently reruns the existing setup Job.
      timeout = window.setTimeout(() => {
        controller.abort();
      }, 120_000);
      while (!stopped()) {
        let delay = 5;
        try {
          const result = await fetchMcpPublication(id, controller.signal);
          if (!active.current || stopped()) return;
          const fresh = !marker || (result.checked_at !== null &&
            Date.parse(result.checked_at) >= Date.parse(marker));
          if (fresh || result.state === "unavailable") setStatus(result);
          if (fresh && (result.state === "published" || result.state === "error")) break;
        } catch (error) {
          if (stopped()) break;
          if (error instanceof ApiRequestError && error.status === 429) {
            delay = Math.max(5, error.retryAfter ?? 60);
            setRetryUntil(Date.now() + delay * 1000);
          } else {
            setStatus({ state: "unavailable", checked_at: null, error_code: null });
            setError("Publication status is unavailable.");
            break;
          }
        }
        await wait(delay, controller.signal);
      }
    } catch (error) {
      if (active.current && !stopped()) {
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
        refresh.current();
      }
    }
  }

  const publication = status ?? initial;
  return (
    <div className="space-y-2" aria-live="polite">
      <button type="button" className="btn btn-sm btn-outline" disabled={busy || !!retryUntil}
        onClick={() => void run(true)}>
        {busy ? discovering ? "Discovering…" : "Checking publication…" : "Discover tools"}
      </button>
      {publication && <p className="max-w-xs text-xs text-muted-foreground">
        {publication.state === "published" ? "Tools published" :
          publication.state === "error" ? "Publication failed. Check the setup Job." :
          publication.state === "unavailable" ? "Publication status unavailable" :
          discoveredAt ? "Discovered; publication pending. Run the setup publication Job." :
          "Tool discovery pending"}
      </p>}
      {!busy && discoveredAt && publication?.state !== "published" && (
        <button type="button" className="btn btn-xs btn-ghost" disabled={!!retryUntil}
          onClick={() => void run(false)}>Check publication</button>
      )}
      {error && <p role="alert" className="max-w-xs text-xs text-error">{error}</p>}
    </div>
  );
}
