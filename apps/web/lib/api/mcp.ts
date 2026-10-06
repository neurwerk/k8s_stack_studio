import { apiGet } from "./client";

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
