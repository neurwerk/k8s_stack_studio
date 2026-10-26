/** Typed API wrapper for per-user call, token, and cost usage. */

import { apiGet } from "@/lib/api/client";
import { gatewayParams } from "@/lib/api/gateway-metadata";
import type { GatewayFilters } from "@/lib/api/gateway-metadata";

export interface UsageMetric {
  state: "known" | "partial" | "unknown";
  reported_sum: number;
  complete_total: number | null;
  known_records: number;
  total_records: number;
}

export interface UsageAccounting {
  tokens: UsageMetric;
  cost_usd: UsageMetric;
}

/** Aggregated usage for a calendar or rolling period. */
export interface UsagePeriod {
  requests: number;
  total_tokens: number;
  cost_usd: number;
  request_scope?: "native_llm_records";
  accounting?: UsageAccounting;
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

export interface UsagePerson extends UsagePeriod {
  user_id: string;
}

export interface UsagePeople {
  timezone: string;
  start_date: string;
  end_date: string;
  users: UsagePerson[];
}

export interface UsageSource extends UsagePeriod {
  id: string | null;
  kind: string | null;
  name?: string | null;
  name_status?: "not_looked_up" | "unavailable" | "resolved";
}

export interface UsagePersonSources {
  user_id: string | null;
  total: UsagePeriod;
  apps: UsageSource[];
  credentials: UsageSource[];
}

export interface UsageSources {
  timezone: string;
  start_date: string;
  end_date: string;
  apps: UsageSource[];
  credentials: UsageSource[];
  people: UsagePersonSources[];
  key_name_enrichment?: {
    eligible_keys: number;
    looked_up_keys: number;
    named_keys: number;
    limit_reached: boolean;
    lookup_failed: boolean;
  };
}

/** Self-or-admin scope is enforced by the API, including identifier discovery. */
export function fetchUsageSources(userId: string | null, range: UsageDateRange, signal?: AbortSignal, filters: GatewayFilters = {}): Promise<UsageSources> {
  const path = userId === null ? "/usage/sources" : `/users/${encodeURIComponent(userId)}/usage/sources`;
  return apiGet<UsageSources>(path, { ...range, ...gatewayParams(filters) }, signal);
}

/** Omit the range to use the server's last 30 calendar days, including today. */
export function fetchUserDailyUsage(
  userId: string,
  range?: UsageDateRange,
  signal?: AbortSignal,
  filters: GatewayFilters = {},
): Promise<UserDailyUsage> {
  const path = `/users/${encodeURIComponent(userId)}/usage/daily`;
  const params = { ...range, ...gatewayParams(filters) };
  return signal ? apiGet<UserDailyUsage>(path, params, signal) : apiGet<UserDailyUsage>(path, params);
}

/** Only usage admins can request an unfiltered aggregation. */
export function fetchAllDailyUsage(
  range?: UsageDateRange,
  signal?: AbortSignal,
  filters: GatewayFilters = {},
): Promise<UserDailyUsage> {
  return apiGet<UserDailyUsage>(
    "/usage/daily",
    { ...range, ...gatewayParams(filters) },
    signal,
  );
}

/** Active principals for the admin selector and per-person breakdown. */
export function fetchUsagePeople(range: UsageDateRange, signal?: AbortSignal, filters: GatewayFilters = {}): Promise<UsagePeople> {
  return apiGet<UsagePeople>("/usage/people", { ...range, ...gatewayParams(filters) }, signal);
}
