import { apiGet } from "./client";

export interface VerifiedSession {
  subject: string;
  realm_roles: string[];
  agentgateway_roles: string[];
  notice_preferences_available: boolean;
  llm_logs_available: boolean;
  mcp_catalog_available?: boolean;
  mcp_connections_available?: boolean;
}

export async function fetchSession(): Promise<VerifiedSession> {
  return apiGet<VerifiedSession>("/session");
}
