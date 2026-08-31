/** Typed API wrapper for the versioned PII Engine Studio contract. */

import { apiGet, apiPost } from "./client";

export type ChatRole = "system" | "developer" | "user" | "assistant" | "tool";

export interface TextPart {
  type: "text";
  text: string;
}

export interface AttachmentPart {
  type:
    | "image_url"
    | "input_audio"
    | "file"
    | "input_image"
    | "input_file"
    | "image"
    | "audio"
    | "resource"
    | "resource_link";
  [key: string]: unknown;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: unknown };
}

export interface ChatMessage {
  role: ChatRole;
  content?: string | (TextPart | AttachmentPart)[] | null;
  name?: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
}

export interface OpenAIChatRequest {
  model: string;
  messages: ChatMessage[];
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  stream?: boolean;
}

export interface OpenAIResponsesRequest {
  model: string;
  input: unknown;
  instructions?: string;
  stream?: boolean;
  previous_response_id?: string;
}

export interface McpRequest {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  params: Record<string, unknown>;
}

export type SupportedRequest = OpenAIChatRequest | OpenAIResponsesRequest | McpRequest;
export type PolicyOverride = Record<string, unknown>;

export interface AnalyzeRequest {
  request: SupportedRequest;
  policy?: PolicyOverride;
}

export interface EvaluateRequest {
  request: SupportedRequest;
  policy?: PolicyOverride;
  simulation?: "deterministic_echo";
}

export type PolicyDecision = "pass" | "block" | "apply_actions" | "reroute";

export interface AnalysisMetadata {
  source: "current_request" | "cached_decision";
  scan_performed: boolean;
  duration_ms: number | null;
  overlap_count: number;
  overlap_resolution: "strictest_action";
  policy_version: string;
  text_leaf_count: number;
  cached_decision_applied: boolean;
}

export interface Notices {
  request: string[];
  response: string[];
}

export interface AnalyzeResponse {
  api_version: "v1";
  decision: PolicyDecision;
  entities: string[];
  entity_counts: Record<string, number>;
  applied_actions: string[];
  remote_allowed: boolean;
  route_class: string | null;
  request: SupportedRequest | null;
  analysis: AnalysisMetadata;
  notices: Notices;
  safety_rule: string | null;
}

export type PolicyAction =
  | "pass"
  | "block"
  | "reroute"
  | "mask"
  | "replace"
  | "redact"
  | "hash"
  | "encrypt"
  | "reversible_replace";
export type EvaluationPathPart = string | number;
export type DetectionSource = "deterministic" | "spacy" | "transformer" | "policy_regex";

export interface PolicyEvaluationIssue {
  stage: "schema" | "merge" | "compile";
  path: EvaluationPathPart[];
  code: string;
  message: string;
}

export interface LogicalDetection {
  path: EvaluationPathPart[];
  start: number;
  end: number;
  entity_type: string;
  score: number;
  source: DetectionSource;
  configured_action: PolicyAction;
  resolved_action: PolicyAction;
}

export interface EffectiveRegion {
  path: EvaluationPathPart[];
  start: number;
  end: number;
  entity_type: string;
  action: PolicyAction;
  source: DetectionSource;
  score: number;
  member_entity_types: string[];
  overlap: boolean;
}

export interface PiiReportRow {
  entity_type: string;
  action: PolicyAction;
  detected_count: number;
  transformed_count: number;
  unique_transformed_count: number;
}

export interface EvaluationDiagnostics {
  logical_detections: LogicalDetection[];
  effective_regions: EffectiveRegion[];
  truncated: boolean;
}

export interface EvaluationSimulation {
  type: "deterministic_echo";
  status: "completed" | "skipped";
  reason: "request_blocked" | null;
  model_called: false;
  model_response: string | null;
  user_response: string | null;
  restored_entity_counts: Record<string, number>;
}

export interface InvalidEvaluateResponse {
  api_version: "v1";
  valid: false;
  issues: PolicyEvaluationIssue[];
  issues_truncated: boolean;
}

export interface ValidEvaluateResponse extends AnalyzeResponse {
  valid: true;
  issues: [];
  issues_truncated: false;
  report: { rows: PiiReportRow[] };
  diagnostics: EvaluationDiagnostics;
  simulation: EvaluationSimulation;
}

export type EvaluateResponse = ValidEvaluateResponse | InvalidEvaluateResponse;

export async function policyEngineAnalyze(
  request: SupportedRequest,
  policy?: PolicyOverride,
): Promise<AnalyzeResponse> {
  const body: AnalyzeRequest = policy ? { request, policy } : { request };
  return apiPost<AnalyzeRequest, AnalyzeResponse>("/policy-engine/analyze", body);
}

export async function policyEngineEvaluate(
  request: SupportedRequest,
  policy?: PolicyOverride,
): Promise<EvaluateResponse> {
  const body: EvaluateRequest = policy ? { request, policy } : { request };
  return apiPost<EvaluateRequest, EvaluateResponse>("/policy-engine/evaluate", body);
}

export interface ActionParamDef {
  name: string;
  type: string;
  default: string;
  description: string;
  options: string[];
}

export interface ActionDef {
  name: string;
  decision: string;
  reversible: boolean;
  severity: "pass" | "fail" | "info" | "warn";
  strictness: number;
  params: ActionParamDef[];
  notes: string;
  exampleInput?: string;
  exampleOutput?: string;
  validation?: string[];
}

export async function getActions(): Promise<ActionDef[]> {
  return apiGet<ActionDef[]>("/policy-engine/actions");
}

export interface PolicyResponse {
  api_version: "v1";
  version: string;
  default_action: string;
  entities: string[];
  safety_rules: string[];
}

/** Fetch shared policy metadata from PII Engine. */
export async function getPolicy(): Promise<PolicyResponse> {
  return apiGet<PolicyResponse>("/policy-engine/policy");
}
