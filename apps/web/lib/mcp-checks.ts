import type { McpCatalogEntry, McpConnectionStatus, McpTool, McpCheckResult } from "./api/mcp";

export interface CheckState {
  result?: McpCheckResult;
  error?: string;
  checkedAt?: string;
  running?: boolean;
}

export interface IntegrationChecks {
  tools: McpTool[] | null;
  checks: Record<string, CheckState>;
  busy: boolean;
  message: string;
  retryUntil: number;
}

interface Driver {
  tools: (id: string, signal: AbortSignal) => Promise<McpTool[]>;
  check: (id: string, check: string, signal: AbortSignal) => Promise<McpCheckResult>;
  error: (error: unknown) => { message: string; retryAfter?: number };
}

export function afterDiscovery(item: McpCatalogEntry, marker?: string): McpCatalogEntry {
  if (marker && item.publication?.state === "published" &&
    (!item.publication.checked_at || !(Date.parse(item.publication.checked_at) > Date.parse(marker)))) {
    return { ...item, publication: { ...item.publication, state: "pending-discovery" } };
  }
  return item;
}

export function skipReason(item: McpCatalogEntry, connection?: McpConnectionStatus): string {
  if (!item.permitted) return "No permission";
  if (item.publication && item.publication.state !== "published") return "Tools not published";
  if (item.authentication_model === "individual-authentication") {
    if (!connection || connection.message) return "Connection status unavailable";
    if (connection.status === "connect required") return "Connect to run checks";
    if (!["connected", "refresh pending"].includes(connection.status)) return "Connection status unavailable";
  }
  return "";
}

export function checkSummary(state?: IntegrationChecks): { label: string; failed: boolean } {
  if (!state) return { label: "Waiting for checks", failed: false };
  const values = Object.values(state.checks);
  const failed = values.filter((value) => value.result?.status === "failed").length;
  const unavailable = values.filter((value) => !!value.error).length;
  const total = state.tools?.reduce((count, tool) => count + Object.keys(tool.checks).length, 0) ?? 0;
  const noun = total === 1 ? "check" : "checks";
  const suffix = `${unavailable ? ` · ${String(unavailable)} unavailable` : ""}${state.busy ? " · checking…" : ""}`;
  if (failed) return { label: `${String(failed)} of ${String(total)} ${noun} failed${suffix}`, failed: true };
  if (unavailable) return { label: `${String(unavailable)} of ${String(total)} ${noun} unavailable${state.busy ? " · checking…" : ""}`, failed: false };
  if (state.busy) return { label: "Checking…", failed: false };
  if (state.message) return { label: state.message, failed: false };
  if (!total) return { label: "No checks configured", failed: false };
  const passed = values.filter((value) => value.result?.status === "passed").length;
  return { label: passed === total ? `${String(total)} ${noun} passed` : `${String(passed)} of ${String(total)} ${noun} completed`, failed: false };
}

// One controller per page visit. Three integration workers; tool calls within each
// integration are sequential. Refresh supersedes results, never overlaps its old run.
export class McpChecks {
  states: Record<string, IntegrationChecks> = {};
  private driver: Driver;
  private changed: (() => void) | null = null;
  private controller: AbortController | null = null;
  private versions = new Map<string, string>();
  private eligible = new Set<string>();
  private generations = new Map<string, number>();
  private queue = new Set<string>();
  private running = new Set<string>();
  private cooldown = 0;

  constructor(driver: Driver) { this.driver = driver; }

  start(changed: () => void) {
    this.changed = changed;
    this.controller = new AbortController();
  }

  stop() {
    this.controller?.abort();
    this.controller = null;
    this.queue.clear();
    this.running.clear();
    this.versions.clear();
    this.eligible.clear();
    this.changed = null;
  }

  sync(items: McpCatalogEntry[], connections: Record<string, McpConnectionStatus>, revisions: Record<string, number>, pending: Record<string, boolean> = {}) {
    const ids = new Set(items.map((item) => item.id));
    for (const id of this.versions.keys()) {
      if (ids.has(id)) continue;
      this.queue.delete(id);
      this.eligible.delete(id);
      this.versions.delete(id);
      this.generations.set(id, (this.generations.get(id) ?? 0) + 1);
      this.states = Object.fromEntries(Object.entries(this.states).filter(([key]) => key !== id));
    }
    for (const item of items) {
      const reason = pending[item.id] ? "Refreshing integration…" : skipReason(item, connections[item.id]);
      const version = `${String(revisions[item.id] ?? 0)}:${reason}`;
      if (this.versions.get(item.id) === version) continue;
      this.versions.set(item.id, version);
      this.generations.set(item.id, (this.generations.get(item.id) ?? 0) + 1);
      const retryUntil = this.states[item.id]?.retryUntil ?? 0;
      this.states[item.id] = { tools: null, checks: {}, busy: !reason, message: reason, retryUntil };
      if (reason) { this.queue.delete(item.id); this.eligible.delete(item.id); }
      else { this.queue.add(item.id); this.eligible.add(item.id); }
    }
    this.changed?.();
    // Deferring also makes React's setup/cleanup/setup replay start no requests.
    queueMicrotask(() => { this.pump(); });
  }

  recheck(id: string) {
    const state = this.states[id];
    if (!this.eligible.has(id) || !state || state.busy || Date.now() < state.retryUntil) return;
    this.generations.set(id, (this.generations.get(id) ?? 0) + 1);
    this.states[id] = { ...state, checks: {}, busy: true, message: "" };
    this.queue.add(id);
    this.changed?.();
    this.pump();
  }

  private pump() {
    const controller = this.controller;
    if (!controller) return;
    for (const id of this.queue) {
      if (this.running.size >= 3) break;
      if (this.running.has(id)) continue;
      this.queue.delete(id);
      this.running.add(id);
      void this.run(id, controller).finally(() => {
        // An obsolete mount must not release a worker from the next mount.
        if (this.controller !== controller) return;
        this.running.delete(id);
        this.pump();
      });
    }
  }

  private async run(id: string, controller: AbortController) {
    const generation = this.generations.get(id);
    const current = () => !controller.signal.aborted && generation === this.generations.get(id);
    const state = this.states[id];
    if (!state) return;
    const ready = async () => {
      while (current() && Date.now() < this.cooldown) {
        await new Promise<void>((resolve) => {
          const done = () => { clearTimeout(timer); controller.signal.removeEventListener("abort", done); resolve(); };
          const timer = setTimeout(done, this.cooldown - Date.now());
          controller.signal.addEventListener("abort", done, { once: true });
        });
      }
      return current();
    };
    const failure = (error: unknown) => {
      const value = this.driver.error(error);
      if (value.retryAfter !== undefined) {
        this.cooldown = Math.max(this.cooldown, Date.now() + value.retryAfter * 1000);
        state.retryUntil = this.cooldown;
      }
      return value.message;
    };
    try {
      if (!await ready()) return;
      const tools = await this.driver.tools(id, controller.signal);
      if (!current()) return;
      state.tools = tools;
      this.changed?.();
      for (const [checkId] of tools.flatMap((tool) => Object.entries(tool.checks))) {
        if (!await ready()) return;
        state.checks[checkId] = { running: true };
        this.changed?.();
        try {
          const result = await this.driver.check(id, checkId, controller.signal);
          if (!current()) return;
          state.checks[checkId] = { result };
        } catch (error) {
          if (!current()) return;
          state.checks[checkId] = { error: failure(error), checkedAt: new Date().toISOString() };
        }
        this.changed?.();
      }
    } catch (error) {
      if (current()) state.message = failure(error);
    } finally {
      if (current()) { state.busy = false; this.changed?.(); }
    }
  }
}
