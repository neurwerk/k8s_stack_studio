import { apiPost } from "@/lib/api/client";

interface ActivityBase {
  id: string;
  startTime: string;
  durationMs: number | null;
  sessionId: string | null;
  metadata: Record<string, unknown>;
  tokens: number | null;
  costUsd: number | null;
}

export interface LlmExchange extends ActivityBase {
  type: "GENERATION";
  name: string | null;
  model: string | null;
  level: string | null;
  input: string | null;
  output: string | null;
}

export interface McpCall extends ActivityBase {
  type: "TOOL";
  server: string | null;
  tool: string;
  parameters: string | null;
  result: string | null;
  status: string | null;
}

export type Activity = LlmExchange | McpCall;
export type ActivityType = "all" | "llm" | "mcp";

export interface ActivityFilters {
  q: string;
  type?: ActivityType;
  start?: string;
  end?: string;
}

/** The server derives the owner from the token and always returns at most ten. */
export function fetchLlmActivity(filters: ActivityFilters): Promise<Activity[]> {
  return apiPost<ActivityFilters, Activity[]>("/me/llm-activity", filters);
}
