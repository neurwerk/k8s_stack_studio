"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import "swagger-ui-react/swagger-ui.css";
import { fetchGateway } from "@/lib/api/gateway";
import type { GatewayEntry, GatewayView } from "@/lib/api/gateway";
import { useVerifiedSession } from "@/lib/auth/session-context";

const groups = [
  ["self-hosted-api-providers", "1. Self-hosted API providers"],
  ["external-api-providers", "2. External API providers"],
  ["external-subscription-providers", "3. External subscription providers"],
  ["mcp-servers", "4. MCP servers"],
] as const;

const SwaggerUI = dynamic(() => import("swagger-ui-react"), { ssr: false });

interface SwaggerSystem {
  preauthorizeApiKey: (name: string, value: string) => void;
  authActions: { logout: (names: string[]) => void };
}

interface ApiOperation {
  method: "get" | "post" | "delete";
  path: string;
  summary: string;
  description?: string;
  body?: Record<string, unknown>;
  parameters?: object[];
}

const jsonBody = (properties: Record<string, unknown>, required: string[] = []) => ({
  required: true,
  content: { "application/json": { schema: { type: "object", properties, required } } },
});

function operations(entry: GatewayEntry): ApiOperation[] {
  const profiles = new Set(entry.destinations.flatMap((destination) => destination.profile_ids));
  if (entry.destinations.some((destination) => destination.kind === "mcp")) {
    return [
      { method: "post", path: "", summary: "MCP JSON-RPC exchange", description: "Stateless Streamable HTTP exchange. Call tools/list to discover the tools this server provides; tool calls use tools/call.",
        parameters: [{ name: "Accept", in: "header", schema: { type: "string", default: "application/json, text/event-stream" }, description: "Accept MCP JSON or SSE responses." }],
        body: jsonBody({ jsonrpc: { type: "string", enum: ["2.0"] }, id: { oneOf: [{ type: "string" }, { type: "integer" }] }, method: { type: "string", example: "tools/list" }, params: { type: "object", additionalProperties: true } }, ["jsonrpc", "method"]) },
      { method: "get", path: "", summary: "MCP event stream", description: "Availability depends on the MCP backend; stateful sessions are not supported." },
      { method: "delete", path: "", summary: "MCP session termination", description: "Availability depends on the MCP backend; stateful sessions are not supported." },
    ];
  }
  const result: ApiOperation[] = [];
  if (profiles.has("openai-model-discovery-v1")) {
    result.push({ method: "get", path: "/models", summary: "List permitted models" },
      { method: "get", path: "/models/{model}", summary: "Retrieve a permitted model" });
  }
  const models = entry.destinations.filter((destination) => destination.kind === "model").map((destination) => destination.id);
  const model = { type: "string", enum: models };
  if (profiles.has("openai-chat-completions-v1")) {
    result.push({ method: "post", path: "/chat/completions", summary: "Create a chat completion",
      body: jsonBody({ model, messages: { type: "array", items: { type: "object", properties: { role: { type: "string" }, content: { type: "string" } }, required: ["role", "content"] } }, stream: { type: "boolean", default: false } }, ["model", "messages"]) });
  }
  if (profiles.has("openai-responses-v1") || profiles.has("openai-codex-responses-v1")) {
    result.push({ method: "post", path: "/responses", summary: "Create a response",
      body: jsonBody({ model, input: { oneOf: [{ type: "string" }, { type: "array", items: { type: "object" } }] }, stream: { type: "boolean", default: false } }, ["model", "input"]) });
  }
  if (profiles.has("anthropic-messages-v1")) {
    result.push({ method: "post", path: "/messages", summary: "Create a message",
      parameters: [{ name: "anthropic-version", in: "header", required: true, schema: { type: "string", default: "2023-06-01" } }],
      body: jsonBody({ model, max_tokens: { type: "integer", minimum: 1 }, messages: { type: "array", items: { type: "object" } } }, ["model", "max_tokens", "messages"]) });
  }
  return result;
}

function endpointSpec(view: GatewayView) {
  const paths: Record<string, Record<string, unknown>> = {};
  for (const [group, title] of groups) {
    for (const entry of view.catalog[group]) {
      const route = entry.routes.find((item) => item.entry_mode === "api" && item.caller_auth_modes.includes("neurwerk_bearer"));
      if (!route) continue;
      const url = new URL(route.url);
      const basePath = url.pathname.replace(/\/$/, "");
      const profileIds = new Set(entry.destinations.flatMap((destination) => destination.profile_ids));
      const limitations = view.catalog.profiles.filter((profile) => profileIds.has(profile.id)).flatMap((profile) => profile.limitations);
      const credentials = entry.destinations.some((destination) => destination.credential_modes.some((mode) => mode.source === "caller_supplied"))
        ? "Caller-supplied provider credentials are separate from your Neurwerk key; company mode may be available for this binding."
        : "";
      for (const operation of operations(entry)) {
        const path = `${basePath}${operation.path}`;
        const parameters = [...(operation.parameters ?? []), ...(operation.path === "/models/{model}" ? [{ name: "model", in: "path", required: true, schema: { type: "string" } }] : [])];
        paths[path] ??= {};
        paths[path][operation.method] = {
          tags: [title], summary: `${entry.display_name} · ${operation.summary}`,
          description: [operation.description, credentials, ...limitations].filter(Boolean).join("\n\n"),
          operationId: `${entry.id}-${operation.method}-${path}`,
          servers: [{ url: url.origin }], parameters,
          ...(operation.body ? { requestBody: operation.body } : {}),
          responses: { "200": { description: "Successful response" }, "401": { description: "Invalid API key" }, "403": { description: "Permission denied" } },
        };
      }
    }
  }
  return {
    openapi: "3.0.3",
    info: { title: "Endpoints", version: "1" },
    tags: groups.map(([, name]) => ({ name })), paths,
    components: { securitySchemes: { NeurwerkKey: { type: "apiKey", in: "header", name: "X-Neurwerk-Authorization", description: "Enter Bearer <your Neurwerk API key>. It is not saved between visits." } } },
    security: [{ NeurwerkKey: [] }],
  };
}

export function GatewayDashboard() {
  const session = useVerifiedSession();
  return <GatewayContent key={`${session.subject}:${session.agentgateway_roles.join(",")}`} subject={session.subject} />;
}

function GatewayContent({ subject }: { subject: string }) {
  const [view, setView] = useState<GatewayView | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiKey, setApiKey] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [ready, setReady] = useState(false);
  const swagger = useRef<SwaggerSystem | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchGateway(false, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setView(value); })
      .catch(() => { if (!controller.signal.aborted) setView(null); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); };
  }, [subject]);

  const spec = useMemo(() => view && endpointSpec(view), [view]);

  if (!spec) return <main className="p-6 text-sm text-muted-foreground" role="status">{loading ? "Loading endpoints…" : "Gateway information unavailable."}</main>;
  return <main className="endpoint-swagger mx-auto max-w-7xl p-4 sm:p-6">
    <h1 className="mb-6 text-2xl font-semibold tracking-tight">Endpoints</h1>
    <form className="mx-5 mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4 sm:p-5" onSubmit={(event) => {
      event.preventDefault();
      if (!apiKey.trim() || !swagger.current) return;
      const key = apiKey.trim().replace(/^Bearer\s+/i, "");
      swagger.current.preauthorizeApiKey("NeurwerkKey", `Bearer ${key}`);
      setAuthorized(true);
    }}>
      <div className="mr-auto flex items-center gap-2 text-sm">
        <label className="font-medium" htmlFor="endpoint-api-key">Neurwerk API key</label>
        <Link href="/api-keys" className="link link-primary">Create here</Link>
      </div>
      <div className="flex w-full flex-wrap items-center justify-end gap-3 sm:w-auto sm:flex-nowrap">
        <input id="endpoint-api-key" type="password" autoComplete="off" spellCheck={false} value={apiKey}
          onChange={(event) => {
            swagger.current?.authActions.logout(["NeurwerkKey"]);
            setAuthorized(false);
            setApiKey(event.target.value);
          }} placeholder="Enter your API key" className="input input-bordered w-full bg-base-100 font-mono text-sm sm:w-64 lg:w-80" />
        <button className="btn btn-primary" type="submit" disabled={!ready || !apiKey.trim() || authorized}>{authorized ? "Authorized" : "Authorize"}</button>
      </div>
      <span role="status" className="sr-only">{authorized ? "Authorized for Try requests" : "Not authorized"}</span>
    </form>
    <SwaggerUI spec={spec} docExpansion="list" defaultModelsExpandDepth={-1} persistAuthorization={false}
      withCredentials={false} supportedSubmitMethods={["get", "post", "delete"]}
      onComplete={(system: SwaggerSystem) => { swagger.current = system; setReady(true); }} />
    <footer className="mx-5 mt-8 border-t border-border pt-3 text-right text-xs text-muted-foreground">
      Powered by <a href="https://swagger.io/" target="_blank" rel="noopener noreferrer" className="link link-primary">swagger.io</a>
    </footer>
  </main>;
}
