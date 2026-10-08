import { apiGet, apiPost } from "./client";
import { ApiRequestError } from "./client";

export interface McpCatalogEntry {
  id: string;
  name: string;
  authentication_model: "no-authentication" | "shared-authentication" | "individual-authentication";
  permitted: boolean;
  connection_status: "status unavailable" | null;
  can_discover?: boolean;
  publication?: McpPublicationStatus | null;
}

export interface McpPublicationStatus {
  state: "pending-discovery" | "published" | "error" | "unavailable";
  checked_at: string | null;
  error_code: string | null;
}

export function fetchMcpPublication(id: string, signal?: AbortSignal): Promise<McpPublicationStatus> {
  return apiGet<McpPublicationStatus>(`/me/mcp/${encodeURIComponent(id)}/publication`, undefined, signal);
}

export function discoverMcp(id: string): Promise<{ discovered_at: string }> {
  return apiPost<Record<string, never>, { discovered_at: string }>(
    `/me/mcp/${encodeURIComponent(id)}/discover`, {},
  );
}

export function fetchMcpConnection(id: string): Promise<McpConnectionStatus> {
  return apiGet<McpConnectionStatus>(`/me/mcp/${encodeURIComponent(id)}/status`);
}

export function fetchMcpCatalog(): Promise<McpCatalogEntry[]> {
  return apiGet<McpCatalogEntry[]>("/me/mcp/catalog");
}

export interface McpConnectionStatus {
  status: "connected" | "refresh pending" | "connect required" | "status unavailable";
  checked_at: string | null;
  retry_after: number | null;
  message: string | null;
}

export interface McpConnectResponse {
  authorization_url: string;
  callback_origin: string;
}

export function fetchMcpConnections(): Promise<Record<string, McpConnectionStatus>> {
  return apiGet<Record<string, McpConnectionStatus>>("/me/mcp/connections");
}

export interface McpCheck {
  name: string;
  tool: string;
  arguments: Record<string, unknown>;
  display: { label: string; field: string } | null;
}

export interface McpTool {
  name: string;
  description: string;
  checks: Record<string, McpCheck>;
}

export interface McpCheckResult {
  status: "passed" | "failed";
  checked_at: string;
  result: string;
  display_label: string | null;
  display_value: string | null;
}

export function fetchMcpTools(id: string): Promise<McpTool[]> {
  return apiPost<Record<string, never>, McpTool[]>(`/me/mcp/${encodeURIComponent(id)}/tools`, {});
}

export function runMcpCheck(id: string, checkId: string): Promise<McpCheckResult> {
  return apiPost<Record<string, never>, McpCheckResult>(
    `/me/mcp/${encodeURIComponent(id)}/checks/${encodeURIComponent(checkId)}`,
    {},
  );
}

export function mcpError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 429)
      return `Too many checks. Try again in ${String(error.retryAfter ?? 60)} seconds.`;
    if (error.status === 401 || error.status === 403)
      return "Access denied. Sign in again or check your permissions.";
    if (error.status === 404) return "This MCP feature is not available.";
  }
  return "Check unavailable. Try again; your saved connection has not been removed.";
}

export function connectMcp(id: string): Promise<McpConnectResponse> {
  return apiPost<Record<string, never>, McpConnectResponse>(
    `/me/mcp/${encodeURIComponent(id)}/connect`,
    {},
  );
}
