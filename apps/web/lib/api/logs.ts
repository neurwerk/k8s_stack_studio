/** Typed API wrapper for the OpenSearch logs viewer endpoints. */

import { apiGet } from "@/lib/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

/** A single log entry returned by the Studio API (mapped from Fluent-Bit). */
export interface LogEntry {
  timestamp: string;
  log: string;
  namespace: string;
  pod: string;
  container: string;
  index: string;
}

/** Response shape of GET /api/logs. */
export interface LogsResponse {
  total: number;
  hits: LogEntry[];
}

/** Filters accepted by the logs endpoint. */
export interface LogsFilter {
  q?: string;
  namespace?: string;
  pod?: string;
  size?: number;
}

// ── Endpoints ─────────────────────────────────────────────────────────────────

/** Search pod logs via OpenSearch (opensearch-admin role required). */
export function fetchLogs(filter: LogsFilter = {}): Promise<LogsResponse> {
  const params: Record<string, string> = {};
  if (filter.q) params.q = filter.q;
  if (filter.namespace) params.namespace = filter.namespace;
  if (filter.pod) params.pod = filter.pod;
  params.size = String(filter.size ?? 100);
  return apiGet<LogsResponse>("/logs", params);
}
