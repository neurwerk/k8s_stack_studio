import { apiPost } from "@/lib/api/client";

export interface LlmExchange {
  id: string;
  startTime: string;
  name: string | null;
  model: string | null;
  level: string | null;
  input: string | null;
  output: string | null;
}

export interface ActivityFilters {
  q: string;
  start?: string;
  end?: string;
}

/** The server derives the owner from the token and always returns at most ten. */
export function fetchLlmActivity(filters: ActivityFilters): Promise<LlmExchange[]> {
  return apiPost<ActivityFilters, LlmExchange[]>("/me/llm-activity", filters);
}
