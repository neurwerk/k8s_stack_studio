"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchGateway } from "@/lib/api/gateway";
import type { GatewayDestination, GatewayProfile, GatewayView } from "@/lib/api/gateway";
import { useVerifiedSession } from "@/lib/auth/session-context";

const groups = [
  ["self-hosted-api-providers", "1. Self-hosted API providers"],
  ["external-api-providers", "2. External API providers"],
  ["external-subscription-providers", "3. External subscription providers"],
  ["mcp-servers", "4. MCP servers"],
] as const;

const providerKeyPages: Record<string, string> = {
  openrouter: "https://openrouter.ai/settings/keys",
  deepseek: "https://platform.deepseek.com/api_keys",
  openai: "https://platform.openai.com/api-keys",
  anthropic: "https://platform.claude.com/docs/en/get-api-key",
};

interface ApiOperation {
  method: "get" | "post" | "delete";
  path: string;
  summary: string;
  description?: string;
  body?: Record<string, unknown>;
  parameters?: object[];
}

const jsonBody = (properties: Record<string, unknown>, required: string[] = [], example?: object) => ({
  required: true,
  content: { "application/json": { schema: { type: "object", properties, required }, ...(example ? { example } : {}) } },
});

function operations(destinations: GatewayDestination[], catalogProfiles: GatewayProfile[]): ApiOperation[] {
  const profiles = new Set(destinations.flatMap((destination) => destination.profile_ids));
  const supports = (profileId: string, operationId: string) => catalogProfiles.some((profile) => profile.id === profileId &&
    profile.operations.some((operation) => operation.id === operationId && operation.support !== "unsupported"));
  if (destinations.some((destination) => destination.kind === "mcp") && supports("mcp-streamable-http-v1", "exchange")) {
    return [
      { method: "post", path: "", summary: "List or call tools", description: "Send tools/list to discover tools. Then send tools/call with a returned tool name and its arguments.",
        parameters: [{ name: "Accept", in: "header", schema: { type: "string", default: "application/json, text/event-stream" }, description: "Accept MCP JSON or SSE responses." }],
        body: jsonBody({ jsonrpc: { type: "string", enum: ["2.0"], description: "JSON-RPC protocol version; always 2.0." }, id: { description: "Request identifier; match this to the response. Use a string or integer.", oneOf: [{ type: "string" }, { type: "integer" }] }, method: { type: "string", enum: ["tools/list", "tools/call"], description: "List available tools first, then call a tool by name." }, params: { type: "object", additionalProperties: true, description: "Method arguments. For tools/call, include name and arguments from tools/list; tools/list can omit params." } }, ["jsonrpc", "id", "method"], { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }) },
    ];
  }
  const result: ApiOperation[] = [];
  if (profiles.has("openai-model-discovery-v1") && supports("openai-model-discovery-v1", "list")) {
    result.push({ method: "get", path: "/models", summary: "List permitted models" });
  }
  if (profiles.has("openai-model-discovery-v1") && supports("openai-model-discovery-v1", "retrieve")) {
    result.push({ method: "get", path: "/models/{model}", summary: "Retrieve a permitted model" });
  }
  const models = destinations.filter((destination) => destination.kind === "model").map((destination) => destination.model ?? destination.id);
   const model = { type: "string", enum: models, description: "Model ID available on this binding. Access still depends on your permissions." };
  const sampleModel = models[0] ?? "select-a-model";
  if (profiles.has("openai-chat-completions-v1") && supports("openai-chat-completions-v1", "create")) {
    result.push({ method: "post", path: "/chat/completions", summary: "Create a chat completion",
       body: jsonBody({ model, messages: { type: "array", minItems: 1, description: "Conversation in order, including the user's prompt and any prior turns.", items: { type: "object", properties: { role: { type: "string", enum: ["system", "developer", "user", "assistant", "tool"], description: "Who sent this message; use user for a new prompt." }, content: { type: "string", minLength: 1, description: "Text of this message." } }, required: ["role", "content"] } }, stream: { type: "boolean", default: false, description: "Return incremental events instead of one complete response when supported." }, temperature: { type: "number", minimum: 0, maximum: 2, description: "Sampling randomness; lower values usually give more consistent output. Provider support varies." }, top_p: { type: "number", minimum: 0, maximum: 1, description: "Nucleus-sampling cutoff; provider support varies. Usually tune this or temperature, not both." }, max_completion_tokens: { type: "integer", minimum: 1, description: "Upper limit on tokens generated in the completion, subject to model and provider limits." } }, ["model", "messages"],
        { model: sampleModel, messages: [{ role: "user", content: "Say hello briefly." }], stream: false }) });
  }
  if ((profiles.has("openai-responses-v1") && supports("openai-responses-v1", "create")) ||
    (profiles.has("openai-codex-responses-v1") && supports("openai-codex-responses-v1", "create"))) {
    const codex = profiles.has("openai-codex-responses-v1");
    result.push({ method: "post", path: "/responses", summary: codex ? "Create a Codex response (two headers required)" : "Create a response",
       description: codex ? "Set both credentials in Authentication above the operations:\n\n| Header | Value |\n| --- | --- |\n| `X-Neurwerk-Authorization` | `Bearer <Neurwerk API key or eligible Keycloak token>` |\n| `Authorization` | `Bearer <Codex session token>` — not an OpenAI API key |" : undefined,
       body: jsonBody({ model, input: { description: "Prompt text, or an array of structured input items for supported models.", oneOf: [{ type: "string", minLength: 1 }, { type: "array", minItems: 1, items: { type: "object" } }] }, instructions: { type: "string", description: "Optional instructions guiding the response." }, stream: { type: "boolean", default: codex, description: "Return incremental events instead of one complete response when supported." }, store: { type: "boolean", description: "Whether the provider may store this response when supported; use false to request no storage." }, max_output_tokens: { type: "integer", minimum: 1, description: "Upper limit on tokens generated in the response, subject to model and provider limits." } }, ["model", "input"],
        { model: sampleModel, input: "Say hello briefly.", stream: codex, ...(codex ? { store: false } : {}) }) });
  }
  if (profiles.has("anthropic-messages-v1") && supports("anthropic-messages-v1", "create")) {
    result.push({ method: "post", path: "/messages", summary: "Create a message",
       parameters: [{ name: "anthropic-version", in: "header", required: true, schema: { type: "string", default: "2023-06-01" }, description: "Anthropic API version for this request." }],
       body: jsonBody({ model, max_tokens: { type: "integer", minimum: 1, description: "Maximum tokens to generate; the response can stop earlier." }, messages: { type: "array", minItems: 1, description: "Conversation turns in order; include at least one user message.", items: { type: "object", properties: { role: { type: "string", enum: ["user", "assistant"], description: "Who sent this message; use user for a new prompt." }, content: { type: "string", description: "Text of this message." } }, required: ["role", "content"] } } }, ["model", "max_tokens", "messages"],
        { model: sampleModel, max_tokens: 128, messages: [{ role: "user", content: "Say hello briefly." }] }) });
  }
  return result;
}

function endpointSpec(view: GatewayView) {
  const paths: Record<string, Record<string, unknown>> = {};
  const tags = groups.map(([, name]) => ({ name }));
  const securitySchemes: Record<string, object> = {
    NeurwerkKey: {
      type: "apiKey", in: "header", name: "X-Neurwerk-Authorization",
      "x-studio-label": "X-Neurwerk-Authorization (required)",
      description: "Use a Neurwerk API key or an eligible Keycloak bearer token. [Create an API key](/api-keys).",
    },
  };
  let providerIndex = 0;
  for (const [group, title] of groups) {
    for (const entry of view.catalog[group]) {
      const route = entry.routes.find((item) => item.entry_mode === "api" && item.caller_auth_modes.includes("neurwerk_bearer"));
      if (!route) continue;
      const tag = title;
      const url = new URL(route.url);
      const basePath = url.pathname.replace(/\/$/, "");
      const destinations = entry.destinations.filter((destination) => destination.endpoint_ids.includes(route.id));
      const profileIds = new Set(destinations.flatMap((destination) => destination.profile_ids));
      const proxyRoute = entry.routes.find((item) => item.entry_mode === "forward_proxy" &&
        item.caller_auth_modes.includes("proxy_basic") && destinations.some((destination) => destination.endpoint_ids.includes(item.id)));
      const limitations = view.catalog.profiles.filter((profile) => profileIds.has(profile.id)).flatMap((profile) => profile.limitations);
      const hasOverride = destinations.some((destination) => destination.kind === "model" &&
        destination.credential_modes.some((mode) => mode.source === "override"));
      const hasGlobal = destinations.some((destination) => destination.kind === "model" &&
        destination.credential_modes.some((mode) => mode.source === "global"));
      const providerHeader = profileIds.has("anthropic-messages-v1") ? "x-api-key" :
        ["openai-chat-completions-v1", "openai-responses-v1", "openai-codex-responses-v1"].some((profile) => profileIds.has(profile)) ? "Authorization" : null;
      const credentialName = profileIds.has("openai-codex-responses-v1") ? "CodexSubscriptionSession" :
        `${entry.display_name.replace(/[^a-zA-Z0-9]/g, "") || "Provider"}ProviderKey`;
      const providerScheme = hasOverride && providerHeader ? `${credentialName}_${String(providerIndex++)}` : null;
      if (providerScheme && providerHeader) {
        const codex = profileIds.has("openai-codex-responses-v1");
        const keyPage = providerKeyPages[entry.provider_id ?? ""];
        const providerName = entry.display_name.replace(/ sample$/i, "").replace(/ API$/i, "");
        securitySchemes[providerScheme] = {
          ...(providerHeader === "Authorization" ? { type: "http", scheme: "bearer" } :
            { type: "apiKey", in: "header", name: providerHeader }),
          "x-studio-label": codex ? "Codex bearer token (required for Codex)" :
            `${providerName} API key (${hasGlobal ? "optional" : "required"})`,
          description: codex
            ? "Use a Codex session token from ChatGPT sign-in. [Learn about sign-in](https://developers.openai.com/codex/auth)."
            : `Use a custom ${providerName} API key ${hasGlobal ? "instead of the globally set credential" : "for this binding"}.${keyPage ? ` [Create an API key](${keyPage}).` : ""}${hasGlobal ? "  \nOptional when a global credential is set. An invalid key does not fall back to the global credential." : ""}`,
        };
      }
      for (const operation of operations(destinations, view.catalog.profiles)) {
        const path = operation.path === "/responses" && basePath.endsWith("/responses") ? basePath : `${basePath}${operation.path}`;
        const parameters = [...(operation.parameters ?? []), ...(operation.path === "/models/{model}" ? [{ name: "model", in: "path", required: true, schema: { type: "string", enum: destinations.filter((destination) => destination.kind === "model").map((destination) => destination.model ?? destination.id) } }] : [])];
        paths[path] ??= {};
        paths[path][operation.method] = {
          tags: [tag], summary: `${entry.display_name} · ${operation.summary}`,
          description: [operation.description,
            proxyRoute && profileIds.has("openai-codex-responses-v1") && operation.path === "/responses"
              ? `**Also available through the inspected forward proxy**\n\nKeep the original Codex request URL and configure your client to use \`${proxyRoute.url}\` as its HTTPS proxy. Use a Neurwerk API key as the proxy password; Codex authentication stays with the client. [Proxy setup and certificate](/forward-proxy).` : undefined,
            providerScheme && operation.method === "post" && !hasGlobal && !profileIds.has("openai-codex-responses-v1")
              ? "A provider API key is required for this operation. Enter it in Authentication above the operations." : undefined,
             ...(group === "mcp-servers" ? [] : limitations)].filter(Boolean).join("\n\n"),
          operationId: `${entry.id}-${operation.method}-${path}`,
          servers: [{ url: url.origin }], parameters,
          ...(providerScheme && operation.method === "post" ? {
            security: hasGlobal ? [{ NeurwerkKey: [], [providerScheme]: [] }, { NeurwerkKey: [] }] :
              [{ NeurwerkKey: [], [providerScheme]: [] }],
          } : {}),
          ...(operation.body ? { requestBody: operation.body } : {}),
          responses: { "200": { description: "Successful response (JSON or, where supported, SSE)" }, "401": { description: "Authentication rejected" }, "403": { description: "Permission denied" } },
        };
      }
    }
  }
  return {
    openapi: "3.0.3",
    info: { title: "Endpoints", version: "1" },
    tags, paths,
    components: { securitySchemes },
    security: [{ NeurwerkKey: [] }],
  };
}

export function GatewayDashboard() {
  const session = useVerifiedSession();
  return <GatewayContent key={`${session.subject}:${session.agentgateway_roles.join(",")}`} subject={session.subject} />;
}

function GatewayReference({ spec }: { spec: ReturnType<typeof endpointSpec> }) {
  const container = useRef<HTMLDivElement>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    type RapiDocElement = HTMLElement & { loadSpec: (value: typeof spec) => Promise<void>; requestUpdate: () => void; updateComplete: Promise<boolean> };
    let doc: RapiDocElement | null = null;
    void import("rapidoc").then(() => {
      if (cancelled || !container.current) return;
      doc = document.createElement("rapi-doc") as RapiDocElement;
      for (const [name, value] of Object.entries({
        "render-style": "view", "show-header": "false", "show-info": "false", "show-side-nav": "false",
        "allow-server-selection": "false", "allow-spec-url-load": "false", "allow-spec-file-load": "false",
        "color-scheme": "light", theme: "#5563AB", radius: "lg", "load-fonts": "false",
        "default-schema-tab": "schema", "schema-description-expanded": "false", "persist-auth": "false",
      })) doc.setAttribute(name, value);
      doc.addEventListener("spec-loaded", (event) => {
        if (cancelled || !doc) return;
        const parsed = (event as CustomEvent<{ securitySchemes?: { securitySchemeId: string; type: string; typeDisplay: string; "x-studio-label"?: string }[] }>).detail;
        for (const scheme of parsed.securitySchemes ?? []) {
          if (scheme["x-studio-label"]) scheme.typeDisplay = scheme["x-studio-label"];
        }
        doc.requestUpdate();
        const loaded = doc;
        void loaded.updateComplete.then(() => {
          if (cancelled || !loaded.shadowRoot) return;
          for (const scheme of parsed.securitySchemes ?? []) {
            const input = loaded.shadowRoot.getElementById(`${scheme.type}-${scheme.securitySchemeId}-api-key-input`) as HTMLInputElement | null;
            if (!input) continue;
            if (scheme.securitySchemeId === "NeurwerkKey") {
              input.placeholder = "Bearer <API key or Keycloak token>";
            } else if (scheme.type === "http" && scheme["x-studio-label"]) {
              input.placeholder = `${scheme["x-studio-label"].replace(/ \(.*\)$/, "")} (Bearer added automatically)`;
            }
          }
        });
      }, { once: true });
      container.current.appendChild(doc);
      void doc.loadSpec(spec).then(() => {
        if (cancelled || !doc?.shadowRoot) return;
        const style = document.createElement("style");
        style.textContent = `
          :host { height: auto !important; overflow: visible !important; }
          .body, .main-content { height: auto; overflow: visible; }
          .operations-root > #operations-top + div { display: none !important; }
          .operations-root > .section-tag { padding-bottom: 16px; }
          .operations-root > .section-tag + .section-tag { margin-top: 24px; }
          #auth { padding: 20px; border: 1px solid var(--border); border-radius: 12px; }
          #auth-table { border-collapse: separate; border-spacing: 0 10px; }
          #auth-table td { padding: 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--card); }
          #auth-table td > div:has(> code) { display: none; }
          #auth-table td > div[style*="max-height:28px"] { max-height: none !important; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
          #auth-table .api-key-input { flex: 1 1 16rem; min-width: 0; border-radius: 6px; background: var(--background); }
          #auth .m-btn { box-shadow: none; }
        `;
        doc.shadowRoot.appendChild(style);
      }).catch(() => { if (!cancelled) setUnavailable(true); });
    }).catch(() => { if (!cancelled) setUnavailable(true); });
    return () => { cancelled = true; doc?.remove(); };
  }, [spec]);

  return <div ref={container} className="endpoint-rapidoc">
    {unavailable && <p role="status" className="text-sm text-muted-foreground">Endpoint reference unavailable.</p>}
  </div>;
}

function GatewayContent({ subject }: { subject: string }) {
  const [view, setView] = useState<GatewayView | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    fetchGateway(false, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setView(value); })
      .catch(() => { if (!controller.signal.aborted) setView(null); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); };
  }, [subject]);

  const spec = useMemo(() => view && endpointSpec(view), [view]);
  const localPreview = view && groups.some(([group]) => view.catalog[group].some((entry) =>
    entry.routes.some((route) => new URL(route.url).hostname === "localhost")));

  if (!spec) return <main className="p-6 text-sm text-muted-foreground" role="status">{loading ? "Loading endpoints…" : "Gateway information unavailable."}</main>;
  return <main className="mx-auto max-w-7xl p-4 sm:p-6">
    <h1 className="mb-6 text-2xl font-semibold tracking-tight">Endpoints</h1>
    <GatewayReference spec={spec} />
    {localPreview && <section className="mt-6 rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground" aria-label="Local preview credentials">
      <h2 className="mb-2 font-semibold text-foreground">Local preview credentials</h2>
      <p>No upstream provider calls. Use these credentials for local requests:</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        <li><code>X-Neurwerk-Authorization</code> (including MCP): <code>Bearer &lt;local Studio Keycloak token&gt;</code>.</li>
        <li>OpenRouter/OpenAI key override: <code>studio-demo-provider-key</code>.</li>
        <li>Codex session: <code>studio-demo-codex-session</code>.</li>
      </ul>
      <p className="mt-2">Never enter real provider credentials in the local preview.</p>
    </section>}
  </main>;
}
