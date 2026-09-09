/** Typed API wrapper for per-user call, token, and cost usage. */

import { apiGet } from "@/lib/api/client";

/** Aggregated usage for a calendar or rolling period. */
export interface UsagePeriod {
  requests: number;
  total_tokens: number;
  cost_usd: number;
}

/** Usage across all periods shown in Studio. */
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

/** Fetch call, token, and cost usage for a user. */
export function fetchUserUsage(userId: string): Promise<UserUsage> {
  return apiGet<UserUsage>(`/users/${userId}/usage`);
}

export interface DailyModelUsage extends UsagePeriod {
  model: string | null;
}

export interface UserDailyUsage {
  timezone: string;
  start_date: string;
  end_date: string;
  today: string;
  days: { date: string; models: DailyModelUsage[] }[];
}

export interface UsageDateRange {
  start: string;
  end: string;
}

/** Omit the range to use the server's last 30 calendar days, including today. */
export function fetchUserDailyUsage(
  userId: string,
  range?: UsageDateRange,
): Promise<UserDailyUsage> {
  return apiGet<UserDailyUsage>(
    `/users/${encodeURIComponent(userId)}/usage/daily`,
    range ? { start: range.start, end: range.end } : undefined,
  );
}
