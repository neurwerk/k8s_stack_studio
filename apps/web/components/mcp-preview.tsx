"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api/client";

type Publication = "published" | "pending-discovery" | "error" | "unavailable";
type Check = "passed" | "failed" | "unavailable";
type Connection = "connected" | "connect required" | "status unavailable";
interface Scenario {
  id: "context7" | "brave" | "github";
  publication: Publication;
  check: Check;
}
interface PreviewState { integrations: Scenario[]; connection: Connection }

export function McpPreview() {
  const [state, setState] = useState<PreviewState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    apiGet<PreviewState>("/dev/mcp/scenarios")
      .then((value) => { setState(value); })
      .catch(() => { setError("Sign in as developer to use the local preview."); });
  }, []);
  async function apply(body: { integration: Scenario["id"]; publication: Publication; check: Check; connection: Connection }) {
    setBusy(true);
    setError("");
    try {
      await apiPost<typeof body, PreviewState>("/dev/mcp/scenario", body);
      window.location.reload();
    } catch {
      setError("Could not change the local MCP preview.");
      setBusy(false);
    }
  }
  async function publish() {
    setBusy(true);
    try {
      await apiPost<Record<string, never>, PreviewState>("/dev/mcp/publish", {});
      window.location.reload();
    } catch {
      setError("Discover GitHub tools first.");
      setBusy(false);
    }
  }
  return (
    <details className="rounded-lg border border-error/25 bg-error/5 p-4">
      <summary className="cursor-pointer text-sm font-medium">Preview scenarios — try failure and pending states</summary>
      <p className="mt-2 text-xs text-muted-foreground">Change a state and reload the page. These controls are only in the local development stack.</p>
      {state?.integrations.map((item) => (
        <div key={item.id} className="mt-3 flex flex-wrap items-center gap-3 text-sm">
          <strong className="min-w-20">{item.id}</strong>
          <span className="text-xs text-muted-foreground">{item.id === "github" ? "Individual key" : "Shared key"}</span>
          <label>Tools <select aria-label={`${item.id} tool publication`} className="select select-sm ml-1" value={item.publication}
            disabled={busy} onChange={(event) => void apply({ integration: item.id, publication: event.target.value as Publication, check: item.check, connection: state.connection })}>
            <option value="published">Published</option><option value="pending-discovery">Pending</option>
            <option value="error">Error</option><option value="unavailable">Unavailable</option>
          </select></label>
          <label>Check <select aria-label={`${item.id} tool check`} className="select select-sm ml-1" value={item.check}
            disabled={busy} onChange={(event) => void apply({ integration: item.id, publication: item.publication, check: event.target.value as Check, connection: state.connection })}>
            <option value="passed">Passed</option><option value="failed">Failed</option><option value="unavailable">Unavailable</option>
          </select></label>
          {item.id === "github" && <label>My connection <select aria-label="GitHub sample connection" className="select select-sm ml-1"
            value={state.connection} disabled={busy} onChange={(event) => void apply({ integration: item.id, publication: item.publication,
              check: item.check, connection: event.target.value as Connection })}>
            <option value="connected">Connected</option><option value="connect required">Not connected</option>
            <option value="status unavailable">Unavailable</option>
          </select></label>}
        </div>
      ))}
      {state?.integrations.find((item) => item.id === "github")?.publication === "pending-discovery" &&
        <button type="button" className="btn btn-sm btn-outline mt-3" disabled={busy} onClick={() => void publish()}>
          Simulate published state
        </button>}
      {error && <p role="alert" className="mt-3 text-xs text-error">{error}</p>}
    </details>
  );
}
