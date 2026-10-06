import { apiGet, apiPost } from "./client";

export interface McpCatalogEntry {
  id: string;
  name: string;
  authentication_model: "no-authentication" | "shared-authentication" | "individual-authentication";
  permitted: boolean;
  connection_status: "status unavailable" | null;
}

export function fetchMcpCatalog(): Promise<McpCatalogEntry[]> {
  return apiGet<McpCatalogEntry[]>("/me/mcp/catalog");
}

export interface McpConnectionStatus {
  status: "connected" | "refresh pending" | "connect required" | "status unavailable";
}

export interface McpConnectResponse {
  authorization_url: string;
  callback_origin: string;
}

export function fetchMcpConnectionStatus(id: string): Promise<McpConnectionStatus> {
  return apiGet<McpConnectionStatus>(`/me/mcp/${encodeURIComponent(id)}/status`);
}

export function connectMcp(id: string): Promise<McpConnectResponse> {
  return apiPost<Record<string, never>, McpConnectResponse>(
    `/me/mcp/${encodeURIComponent(id)}/connect`,
    {},
  );
}
