import { apiGet } from "./client";

export interface VerifiedSession {
  subject: string;
  realm_roles: string[];
  agentgateway_roles: string[];
}

export async function fetchSession(): Promise<VerifiedSession> {
  return apiGet<VerifiedSession>("/session");
}
