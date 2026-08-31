/** Typed API wrapper for Langfuse per-user token and cost usage. */

import { apiGet } from "@/lib/api/client";

/** Aggregated usage for a calendar or rolling period. */
export interface UsagePeriod {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

/** Langfuse usage across all periods shown in Studio. */
export interface UserUsage {
  total: UsagePeriod;
  this_month: UsagePeriod;
  last_month: UsagePeriod;
  last_30_days: UsagePeriod;
  this_week: UsagePeriod;
  last_week: UsagePeriod;
  last_7_days: UsagePeriod;
  today: UsagePeriod;
  last_24_hours: UsagePeriod;
}

/** Fetch Langfuse token and cost usage for a user. */
export function fetchUserUsage(userId: string): Promise<UserUsage> {
  return apiGet<UserUsage>(`/users/${userId}/usage`);
}
