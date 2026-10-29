import type { GatewayFilters } from "@/lib/api/gateway-metadata";
import { billingLabels } from "@/lib/api/gateway-metadata";

const selectors = [
  ["credential_kind", "Platform key kind", { personal: "Personal API key", managed: "Managed API key" }],
  ["billing_classification", "Billing", billingLabels],
  ["provider_credential_source", "Provider credential", { global: "Global credential", override: "Override credential", none: "No provider credential" }],
  ["entry_mode", "Entry mode", { api: "API", forward_proxy: "Forward proxy" }],
  ["destination_kind", "Destination kind", { model: "Model", mcp: "MCP", application: "Application" }],
] as const;

const identifiers = [
  ["app_id", "Originating OIDC app ID"], ["credential_id", "Platform key ID"],
  ["destination_id", "Destination ID"], ["provider_id", "Provider ID"], ["binding_id", "Binding ID"],
  ["protocol_profile", "Protocol profile"], ["operation_id", "Operation ID"], ["policy_revision", "Policy revision"],
  ["requested_model", "Requested model"], ["resolved_model", "Resolved model"], ["request_id", "Request ID"],
] as const;

export function GatewayClassificationFilters({ value, onChange }: {
  value: GatewayFilters; onChange: (value: GatewayFilters) => void;
}) {
  return <fieldset className="min-w-0 space-y-3">
    <legend className="mb-2 text-sm font-medium">Gateway classification</legend>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {selectors.map(([key, label, options]) => <label key={key} className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
        {label}
        <select aria-label={label} className="select select-bordered w-full bg-base-100 text-sm" value={value[key] ?? ""}
          onChange={(event) => { onChange({ ...value, [key]: event.target.value }); }}>
          <option value="">All</option>
          {Object.entries(options).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </label>)}
    </div>
    <details>
      <summary className="cursor-pointer text-xs text-muted-foreground">Exact identifiers</summary>
      <div className="mt-2 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {identifiers.map(([key, label]) => <label key={key} className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
          {label}
          <input aria-label={label} className="input input-bordered w-full bg-base-100 text-sm" maxLength={255} value={value[key] ?? ""}
            onChange={(event) => { onChange({ ...value, [key]: event.target.value }); }} />
        </label>)}
      </div>
    </details>
    <p className="text-xs text-muted-foreground">Exact matches use recorded metadata. Older records without a selected field are excluded. Override credentials do not prove who pays or subscription billing.</p>
  </fieldset>;
}
