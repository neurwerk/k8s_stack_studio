"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, CircleAlert, RefreshCw, ShieldCheck } from "lucide-react";
import { McpConnection } from "@/components/mcp-connection";
import { McpPreview } from "@/components/mcp-preview";
import { fetchMcpConnection } from "@/lib/api/mcp";
import type { McpConnectionStatus } from "@/lib/api/mcp";
import { useVerifiedSession } from "@/lib/auth/session-context";
import { changeMcp, fetchMcpSetup, fetchMcpSetupTools, operationMessage, publishMcp, setupError } from "@/lib/api/mcp-setup";
import type { McpSetupStatus } from "@/lib/api/mcp-setup";

type ServerId = string;

interface ToolSample { name: string; description: string }
interface ServerSample {
  id: ServerId;
  name: string;
  tools: ToolSample[];
}

const SERVERS: ServerSample[] = [
  {
    id: "context7", name: "Context7",
    tools: [
      { name: "resolve-library-id", description: "Find the matching documentation library." },
      { name: "query-docs", description: "Search the selected library's current documentation for a specific programming question. Results may include several relevant sections, examples and references. Choose a library ID first, then describe the topic in enough detail to find the right pages." },
    ],
  },
  {
    id: "brave", name: "Brave Search",
    tools: [
      { name: "brave_web_search", description: "Search public web pages." },
      { name: "brave_local_search", description: "Find places and local results." },
    ],
  },
  {
    id: "github", name: "GitHub",
    tools: [
      { name: "get_me", description: "Show the connected person's GitHub account." },
      { name: "get_file_contents", description: "Read a permitted repository file." },
      { name: "search_repositories", description: "Search repositories visible to the caller." },
    ],
  },
];

const PREVIEW = process.env.NEXT_PUBLIC_STUDIO_MCP_PREVIEW === "true";
const SAMPLES: McpSetupStatus[] = SERVERS.map((server) => ({
  ...server, url: `https://mcp.example.test/${server.id}`,
  credential: { owner: server.id === "github" ? "individual" : "shared", required: server.id !== "context7", method: "" },
  revision: 0, selected_tools: server.tools.map((tool) => tool.name),
  published_tools: server.tools.map((tool) => tool.name), enabled: true,
  publication_uncertain: false, published_at: null,
  key_configured: server.id === "brave", refreshed_at: null, updated_at: null,
  operation: null, available: true,
}));

function authLabel(server: McpSetupStatus): string {
  return server.credential.owner === "individual" ? "Individual key" : server.credential.owner === "shared" ? "Shared key" : "No key";
}

interface Draft {
  selected: string[];
  message: string;
  exampleKey: string;
  removeKey: boolean;
  revision: number;
  dirty: boolean;
}

type Action = "publish" | "disable" | "refresh";

function initialDraft(server: McpSetupStatus): Draft {
  return { selected: server.selected_tools, message: "", exampleKey: "", removeKey: false,
    revision: server.revision, dirty: false };
}

export default function AdminMcpPage() {
  const session = useVerifiedSession();
  const allowed = (session.mcp_setup_available === true || (PREVIEW && session.mcp_catalog_available === true)) &&
    session.realm_roles.includes("mcp-admin");
  if (!allowed) {
    return <p className="p-6 text-sm text-muted-foreground">MCP administrator access is required.</p>;
  }
  return <AdminMcpSetup key={session.subject} />;
}

function AdminMcpSetup() {
  const session = useVerifiedSession();
  const [selectedId, setSelectedId] = useState<ServerId>(PREVIEW ? "context7" : "");
  const [servers, setServers] = useState<McpSetupStatus[]>(PREVIEW ? SAMPLES : []);
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries((PREVIEW ? SAMPLES : []).map((server) => [server.id, initialDraft(server)])));
  const [connections, setConnections] = useState<Record<string, { value: McpConnectionStatus | null; error: boolean }>>({});
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!PREVIEW);
  const [sending, setSending] = useState<{ id: string; kind: Action } | null>(null);
  const [toolReload, setToolReload] = useState(0);
  const [toolResults, setToolResults] = useState<Record<string, { revision: number; error: string }>>({});
  const toolsLoading = !PREVIEW && toolResults[selectedId]?.revision !== toolReload;
  const toolsError = toolsLoading ? "" : toolResults[selectedId]?.error ?? "";
  const connection = connections[selectedId]?.value;
  const connectionError = connections[selectedId]?.error;
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (PREVIEW) return;
    const next = await fetchMcpSetup(signal);
    if (!active.current || signal?.aborted) return;
    setServers((previous) => next.map((server) => ({ ...server,
      tools: previous.find((item) => item.id === server.id)?.tools ?? [] })));
    setDrafts((previous) => Object.fromEntries(next.map((server) => {
      const old = previous[server.id];
      const running = server.operation?.state === "queued" || server.operation?.state === "applying";
      return [server.id, old && (old.dirty || running) ? old : initialDraft(server)];
    })));
    setSelectedId((current) => next.some((item) => item.id === current) ? current : next[0]?.id ?? "");
    setError("");
    setLoading(false);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((cause: unknown) => {
      if (!controller.signal.aborted) { setError(setupError(cause)); setLoading(false); }
    });
    return () => { controller.abort(); };
  }, [load]);

  const pending = servers.some((item) => item.operation?.state === "queued" || item.operation?.state === "applying");
  useEffect(() => {
    if (PREVIEW || !pending) return;
    const controller = new AbortController();
    let fetching = false;
    const timer = window.setInterval(() => {
      if (fetching) return;
      fetching = true;
      void load(controller.signal).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(setupError(cause));
      }).finally(() => { fetching = false; });
    }, 2000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [pending, load]);

  const server = servers.find((item) => item.id === selectedId);
  const individual = server?.credential.owner === "individual";
  const canInvoke = PREVIEW || (session.agentgateway_roles.includes("llm:invoke") &&
    session.agentgateway_roles.includes(`mcp:${selectedId}:invoke`));

  const readConnection = useCallback(() => {
    if (!individual || !canInvoke) return;
    fetchMcpConnection(selectedId)
      .then((value) => { if (active.current) setConnections((current) => ({ ...current, [selectedId]: { value, error: false } })); })
      .catch(() => { if (active.current) setConnections((current) => ({ ...current, [selectedId]: { value: null, error: true } })); });
  }, [selectedId, individual, canInvoke]);

  useEffect(readConnection, [readConnection]);

  useEffect(() => {
    if (PREVIEW || !selectedId) return;
    const controller = new AbortController();
    void fetchMcpSetupTools(selectedId, controller.signal).then((tools) => {
      if (controller.signal.aborted) return;
      setServers((current) => current.map((item) => item.id === selectedId ? { ...item, tools } : item));
      setDrafts((current) => {
        const draft = current[selectedId];
        return draft ? { ...current, [selectedId]: { ...draft,
          selected: draft.selected.filter((name) => tools.some((tool) => tool.name === name)) } } : current;
      });
      setToolResults((current) => ({ ...current, [selectedId]: { revision: toolReload, error: "" } }));
    }).catch((cause: unknown) => { if (!controller.signal.aborted) setToolResults((current) => ({
      ...current, [selectedId]: { revision: toolReload, error: setupError(cause) },
    })); });
    return () => { controller.abort(); };
  }, [selectedId, toolReload]);

  const draft = drafts[selectedId];
  const busy = !!sending || server?.operation?.state === "queued" || server?.operation?.state === "applying";
  const keyConfigured = !!server?.key_configured && !draft?.removeKey;
  const keyReady = !server?.credential.required || individual || keyConfigured || !!draft?.exampleKey.trim();

  function update(id: ServerId, change: Partial<Draft>) {
    setDrafts((current) => current[id] ? ({ ...current, [id]: { ...current[id], ...change } }) : current);
  }

  function select(id: ServerId) {
    setSelectedId(id);
    setConfirmDisable(false);
  }

  function toggleTool(name: string) {
    if (!draft) return;
    update(selectedId, {
      selected: draft.selected.includes(name)
        ? draft.selected.filter((tool) => tool !== name)
        : [...draft.selected, name],
      message: "", dirty: true,
    });
  }

  async function act(kind: Action) {
    if (!draft || !server || busy) return;
    const id = selectedId;
    setConfirmDisable(false);
    if (PREVIEW) {
      setServers((current) => current.map((item) => item.id !== id ? item : {
        ...item,
        ...(kind === "publish" ? { selected_tools: draft.selected, published_tools: draft.selected,
          enabled: !!draft.selected.length, key_configured: keyConfigured || !!draft.exampleKey.trim() } : {}),
        ...(kind === "disable" ? { enabled: false, published_tools: [] } : {}),
        ...(kind === "refresh" ? { refreshed_at: new Date().toISOString() } : {}),
      }));
      update(id, { message: "Saved locally. No live changes.",
        ...(kind === "publish" ? { exampleKey: "", removeKey: false, dirty: false } : {}) });
      return;
    }
    setSending({ id, kind });
    update(id, { message: "", ...(kind === "publish" ? { exampleKey: "" } : {}) });
    try {
      const change = { revision: draft.revision, operation_id: crypto.randomUUID() };
      const operation = kind === "publish" ? await publishMcp(id, { ...change,
        selected_tools: draft.selected, api_key: draft.exampleKey,
        key_action: draft.exampleKey.trim() ? "replace" : draft.removeKey ? "remove" : "keep" })
        : await changeMcp(id, kind, change);
      if (!active.current) return;
      setServers((current) => current.map((item) => item.id === id ? { ...item, operation } : item));
      // Refresh reserves a new revision too. Preserve unsaved choices, but advance
      // only our own accepted change; another admin's changes still require reload.
      update(id, { revision: change.revision + 1,
        ...(kind === "publish" ? { dirty: false, removeKey: false } : {}) });
      await load();
      if (kind === "refresh") setToolReload((value) => value + 1);
    } catch (cause) {
      if (active.current) setError(setupError(cause));
    } finally {
      if (active.current) setSending(null);
    }
  }

  function reload() {
    setDrafts({});
    void load().catch((cause: unknown) => { if (active.current) setError(setupError(cause)); });
    setToolReload((value) => value + 1);
  }

  if (loading) return <p className="p-6 text-sm">Loading MCP Setup…</p>;
  if (!server || !draft) return <div className="space-y-3 p-6 text-sm">
    <p>{error || "No MCP servers are installed."}</p>
    <button type="button" className="btn btn-sm btn-outline" onClick={reload}>Reload status</button>
  </div>;

  const changed = draft.selected.length !== server.published_tools.length ||
    draft.selected.some((name) => !server.published_tools.includes(name)) ||
    !!draft.exampleKey.trim() || draft.removeKey;

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">MCP Setup</h1>
      </header>
      {error && <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-error">
        <p>{error}</p><button type="button" className="btn btn-sm btn-outline" onClick={reload}>Reload status</button>
      </div>}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
        <nav aria-label="MCP servers" className="card border border-border bg-card p-3">
          <h2 className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Servers</h2>
          <div className="space-y-1">
            {servers.map((item) => {
              return (
                <button key={item.id} type="button" onClick={() => { select(item.id); }}
                  aria-current={selectedId === item.id ? "page" : undefined}
                  className={`w-full rounded-lg px-3 py-3 text-left transition-colors ${selectedId === item.id
                    ? "bg-primary/10 text-primary" : "hover:bg-muted"}`}>
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-medium">{item.name}</span>
                    <span className={`badge badge-sm ${item.enabled && !item.publication_uncertain ? "badge-success" : "badge-ghost"}`}>
                      {item.publication_uncertain ? "Unconfirmed" : item.enabled ? "Enabled" : "Disabled"}
                    </span>
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                      {authLabel(item)} · {item.published_tools.length} tools {item.publication_uncertain ? "last confirmed" : "published"}
                  </span>
                </button>
              );
            })}
          </div>
        </nav>

        <div className="min-w-0 space-y-5">
          <section className="card border border-border bg-card p-5 sm:p-6" aria-labelledby="selected-server">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="selected-server" className="text-xl font-semibold">{server.name}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{authLabel(server)}</p>
              </div>
              {!server.enabled && <span className="badge badge-outline">Disabled</span>}
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {[
                ["1", "Set up server"], ["2", "Review tools"], ["3", "Publish changes"],
              ].map(([number, label]) => (
                <div key={number} className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{number}</span>
                  {label}
                </div>
              ))}
            </div>
          </section>

          <section className="card space-y-4 border border-border bg-card p-5 sm:p-6" aria-labelledby="setup-heading">
            <h3 id="setup-heading" className="text-base font-semibold">1 · Server setup</h3>
            <div className="max-w-xl space-y-1 text-sm">
              <p className="font-medium">MCP server URL</p>
              <p className="break-all rounded-lg border border-border bg-muted/30 px-3 py-2 font-mono text-xs select-text">
                {server.url}
              </p>
            </div>
            {server.credential.owner === "shared" && <div className="space-y-2 text-sm">
              <label className="block max-w-xl space-y-1">
                <span className="block font-medium">{keyConfigured ? "Replace API key" : "API key"}
                  {server.credential.required && <><span className="text-error" aria-hidden="true"> *</span><span className="sr-only"> (required)</span></>}
                </span>
                <input type="password" autoComplete="new-password" className="input w-full"
                  value={draft.exampleKey} required={server.credential.required && !keyConfigured} disabled={busy}
                  onChange={(event) => { update(selectedId, { exampleKey: event.target.value, message: "", dirty: true }); }} />
              </label>
              {(draft.exampleKey.trim() || keyConfigured || server.credential.required || draft.removeKey) &&
                <p className="text-xs text-muted-foreground">{draft.exampleKey.trim()
                  ? "Key ready to publish." : draft.removeKey ? "Key will be removed on Publish." : keyConfigured ? "Key configured." : "Required before publishing."}</p>}
              {!server.credential.required && keyConfigured && <button type="button" disabled={busy}
                className="link link-primary text-xs" onClick={() => { update(selectedId, {
                  exampleKey: "", removeKey: true, message: "", dirty: true,
                }); }}>Remove API key</button>}
            </div>}
          </section>

          <section className="card space-y-4 border border-border bg-card p-5 sm:p-6" aria-labelledby="tools-heading">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <h3 id="tools-heading" className="text-base font-semibold">2 · Available tools</h3>
              <div className="flex flex-col items-end gap-2">
                <button type="button" className="btn btn-sm btn-outline w-36"
                  disabled={busy || !canInvoke || !server.available ||
                    (individual ? connection?.status !== "connected" : server.credential.required && !server.key_configured)}
                  onClick={() => { void act("refresh"); }}>
                  <RefreshCw className="h-4 w-4" aria-hidden /> Refresh tools
                </button>
                {individual && canInvoke && <McpConnection key={selectedId} id={selectedId} status={connection?.status}
                  onRefresh={readConnection} confirmReauthorize />}
              </div>
            </div>
            {individual && connectionError &&
              <p role="alert" className="text-xs text-error">Connection status unavailable.</p>}
            {server.refreshed_at && <p className="text-xs text-muted-foreground">Last refreshed: {new Date(server.refreshed_at).toLocaleString()}</p>}
            {individual && connection?.status !== "connected" &&
              <p className="text-xs text-muted-foreground">Connect your own {server.name} account to refresh its tools.</p>}
            {toolsError && <p role="alert" className="text-xs text-error">{toolsError}</p>}
            {toolsLoading && <p className="text-xs text-muted-foreground">Loading tools…</p>}
            {!toolsLoading && !server.tools.length && <p className="text-sm text-muted-foreground">No tools discovered yet.</p>}
            <div className="divide-y divide-border rounded-lg border border-border">
              {server.tools.map((tool) => (
                <div key={`${selectedId}-${tool.name}`} className="flex items-start gap-3 p-4 hover:bg-muted/30">
                  <input id={`mcp-tool-${selectedId}-${tool.name}`} type="checkbox" className="checkbox checkbox-primary checkbox-sm mt-0.5"
                    checked={draft.selected.includes(tool.name)} disabled={busy || toolsLoading} onChange={() => { toggleTool(tool.name); }} />
                  <div className="min-w-0 flex-1">
                    <label htmlFor={`mcp-tool-${selectedId}-${tool.name}`} className="block cursor-pointer break-all font-mono text-sm">{tool.name}</label>
                    <ToolDescription description={tool.description} />
                  </div>
                  <span className="badge badge-ghost badge-sm shrink-0">
                      {server.publication_uncertain ? "Unconfirmed" : server.published_tools.includes(tool.name) && server.enabled ? "Published" : "Not published"}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{draft.selected.length} selected · {server.published_tools.length} {server.publication_uncertain ? "last confirmed" : "published"}</p>
          </section>

          <section className="card space-y-4 border border-border bg-card p-5 sm:p-6" aria-labelledby="publish-heading">
            <div>
              <h3 id="publish-heading" className="text-base font-semibold">3 · Publish or disable</h3>
              <p className="text-sm text-muted-foreground">Publish the chosen tools for permitted users, or disable this server for everyone.</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" className="btn btn-primary" disabled={busy || !keyReady || !server.available ||
                (server.enabled && !changed && server.operation?.state !== "failed")} onClick={() => { void act("publish"); }}>
                <ShieldCheck className="h-4 w-4" aria-hidden /> Publish
              </button>
              {(server.enabled || server.publication_uncertain) && <button type="button" className="btn btn-outline btn-error" disabled={busy} onClick={() => { setConfirmDisable(true); }}>
                Disable server
              </button>}
            </div>
            {confirmDisable && <div className="rounded-lg border border-error/40 bg-error/5 p-4 text-sm">
              <p className="font-medium">Disable {server.name} for everyone?</p>
              <div className="mt-3 flex gap-2">
                <button type="button" className="btn btn-sm btn-error" onClick={() => { void act("disable"); }}>Disable server</button>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => { setConfirmDisable(false); }}>Cancel</button>
              </div>
            </div>}
            {server.publication_uncertain && <p role="status" className="text-sm text-muted-foreground">
              Live tool membership is not confirmed. Refresh tools or retry Publish / Disable.
            </p>}
            {sending?.id === selectedId ? <p role="status" className="text-sm text-muted-foreground">
              {sending.kind === "refresh" ? "Refreshing tools…" : sending.kind === "disable" ? "Disabling…" : "Publishing…"}
            </p> : server.operation && <p role={server.operation.state === "failed" ? "alert" : "status"}
              className={`text-sm ${server.operation.state === "failed" ? "text-error" : "text-muted-foreground"}`}>
              {operationMessage(server)}
            </p>}
          </section>
        </div>
      </div>

      {PREVIEW && <><hr className="border-border" />
      <section aria-label="Development preview" className="space-y-4 rounded-lg border border-error/25 bg-error/5 p-5">
        <div className="flex items-start gap-3 text-sm">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-error" aria-hidden />
          <div className="space-y-1">
            <h2 className="font-semibold">Development preview</h2>
            <p>This page uses sample URLs and tools. Changes are only in browser memory:
              publishing or disabling here does not change live access. Do not enter real credentials.</p>
            <p>Refresh does not contact a provider. Publishing an example key only keeps its configured status;
              the entered text is discarded on Publish. No key is sent to OpenBao or a provider.
              </p>
          </div>
        </div>
        {draft.message && <p role="status" className="flex items-center gap-2 text-sm">
          <Check className="h-4 w-4 shrink-0" aria-hidden /> {server.name}: {draft.message}
        </p>}
        <McpPreview />
      </section>
      </>}
    </div>
  );
}

function ToolDescription({ description }: { description: string }) {
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const text = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (expanded || !text.current) return;
    const element = text.current;
    const measure = () => { setOverflowing(element.scrollHeight > element.clientHeight + 1); };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => { observer.disconnect(); };
  }, [description, expanded]);

  return (
    <div className="mt-1 text-xs text-muted-foreground">
      <p ref={text} className={`whitespace-pre-wrap break-words ${expanded ? "" : "line-clamp-3"}`}>{description || "—"}</p>
      {(overflowing || expanded) && <button type="button" className="link link-primary mt-1 text-xs font-normal"
        aria-expanded={expanded} onClick={() => { setExpanded(!expanded); }}>
        {expanded ? "Show less" : "Show more"}
      </button>}
    </div>
  );
}
