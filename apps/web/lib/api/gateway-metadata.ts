/** Exact normalized metadata filters; the server always supplies the principal. */
export interface GatewayFilters {
  entry_mode?: string;
  destination_kind?: string;
  destination_id?: string;
  provider_id?: string;
  binding_id?: string;
  protocol_profile?: string;
  operation_id?: string;
  provider_credential_source?: string;
  policy_revision?: string;
  requested_model?: string;
  resolved_model?: string;
  billing_classification?: string;
  request_id?: string;
}

export interface GatewayMetadata {
  entry_mode: string | null;
  destination_kind: string | null;
  destination_id: string | null;
  provider_id: string | null;
  binding_id: string | null;
  protocol_profile: string | null;
  operation_id: string | null;
  provider_credential_source: string | null;
  policy_revision: string | null;
  requested_model: string | null;
  resolved_model: string | null;
  billing_classification: "company_api" | "personal_api" | "subscription" | "unknown";
  request_id: string | null;
  token_usage_known: boolean | null;
  cost_known: boolean | null;
}

export const billingLabels: Record<string, string> = {
  company_api: "Company API", personal_api: "Personal API", subscription: "Subscription", unknown: "Unknown billing",
};

export function gatewayParams(filters: GatewayFilters): Record<string, string> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== ""));
}
