import { apiGet, apiPost, ApiRequestError } from "./client";

export interface McpSetupTool { name: string; description: string }
export interface McpOperation {
  id: string;
  kind: "publish" | "disable" | "refresh";
  state: "queued" | "applying" | "succeeded" | "failed";
  phase: string;
  error_code: string | null;
  started_at: string;
  updated_at: string;
  actor: string;
}

export interface McpSetupStatus {
  id: string;
  name: string;
  url: string;
  credential: { owner: "none" | "shared" | "individual"; required: boolean; method: string };
  revision: number;
  selected_tools: string[];
  published_tools: string[];
  enabled: boolean;
  publication_uncertain: boolean;
  published_at: string | null;
  key_configured: boolean;
  refreshed_at: string | null;
  updated_at: string | null;
  operation: McpOperation | null;
  available: boolean;
  tools: McpSetupTool[];
}

export interface McpChange { revision: number; operation_id: string }
export interface McpPublish extends McpChange {
  selected_tools: string[];
  key_action: "keep" | "replace" | "remove";
  api_key: string;
}

export function fetchMcpSetup(signal?: AbortSignal): Promise<McpSetupStatus[]> {
  return apiGet("/admin/mcp", undefined, signal);
}
export function fetchMcpSetupTools(id: string, signal?: AbortSignal): Promise<McpSetupTool[]> {
  return apiGet(`/admin/mcp/${encodeURIComponent(id)}/tools`, undefined, signal);
}
export function publishMcp(id: string, body: McpPublish): Promise<McpOperation> {
  return apiPost(`/admin/mcp/${encodeURIComponent(id)}/publish`, body);
}
export function changeMcp(id: string, kind: "disable" | "refresh", body: McpChange): Promise<McpOperation> {
  return apiPost(`/admin/mcp/${encodeURIComponent(id)}/${kind}`, body);
}
export function setupError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 409) return "Setup changed or an action is running. Reload status and retry.";
    if (error.status === 401 || error.status === 403) return "Access denied. Check your permissions.";
    if (error.status === 422) return "Check the API key and selected tools.";
  }
  return "MCP Setup is unavailable. Reload status and try again.";
}

const ERRORS: Record<string, string> = {
  "api-key-required": "Enter the required API key and Publish.",
  "key-entry-required": "The key was not saved. Enter it again and Publish.",
  "activation-timeout": "The key has not reached the running server. Retry Publish.",
  "credential-store-unavailable": "The key store is unavailable. Retry Publish.",
  "credential-changed": "The API key changed during publication. Retry Publish.",
  "tools-changed-refresh-required": "The tool list changed. Refresh tools and Publish again.",
  "refresh-failed": "Refresh failed. Check the key or your connection, then retry.",
  "refresh-interrupted": "Refresh was interrupted. Refresh tools again.",
  "native-unavailable": "The MCP service is unavailable. Retry the action.",
  "publication-unconfirmed": "Publication could not be confirmed. Retry Publish.",
};

export function operationMessage(server: McpSetupStatus): string {
  const operation = server.operation;
  if (!operation) return "";
  if (operation.state === "failed") return ERRORS[operation.error_code ?? ""] ?? "The action failed. Check server setup and retry.";
  if (operation.state === "succeeded") {
    if (operation.kind === "disable") return "Server disabled. Your tool selection is saved.";
    if (operation.kind === "refresh") return "Tool list refreshed.";
    return server.enabled ? "Published." : "Configured. Select tools and Publish to make them available.";
  }
  if (operation.phase === "waiting-for-key-activation") return "Waiting for the API key to reach the running server…";
  return operation.kind === "disable" ? "Disabling…" : operation.kind === "refresh" ? "Refreshing tools…" : "Publishing…";
}
