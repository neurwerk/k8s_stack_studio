/** Typed API wrapper for the OpenSearch logs viewer endpoints. */

import { apiGet } from "@/lib/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

export const LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "FATAL", "UNKNOWN"] as const;
export type LogLevel = typeof LOG_LEVELS[number];
export const FAILURE_TYPES = {
  timeout: "Timeout",
  connection_error: "Connection failure",
  upstream_error: "Upstream failure",
  processing_error: "Processing failure",
  background_error: "Background failure",
  upload_error: "Upload failure",
  document_error: "Document failure",
  stream_error: "Stream failure",
  application_error: "Application failure",
} as const;
export type FailureType = keyof typeof FAILURE_TYPES;

/** A single log entry returned by the Studio API (mapped from Fluent-Bit). */
export interface LogEntry {
  timestamp: string;
  log: string;
  namespace: string;
  pod: string;
  container: string;
  index: string;
  level?: LogLevel;
  failure_type?: FailureType | null;
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
  start?: string;
  end?: string;
  level?: LogLevel;
  failure_type?: FailureType;
}

// ── Endpoints ─────────────────────────────────────────────────────────────────

/** Search pod logs via OpenSearch (opensearch-admin role required). */
export function fetchLogs(filter: LogsFilter = {}): Promise<LogsResponse> {
  const params: Record<string, string> = {};
  if (filter.q) params.q = filter.q;
  if (filter.namespace) params.namespace = filter.namespace;
  if (filter.pod) params.pod = filter.pod;
  if (filter.start) params.start = filter.start;
  if (filter.end) params.end = filter.end;
  if (filter.level) params.level = filter.level;
  if (filter.failure_type) params.failure_type = filter.failure_type;
  params.size = String(filter.size ?? 100);
  return apiGet<LogsResponse>("/logs", params);
}
