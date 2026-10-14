import type { CredentialSource, GatewayView, HealthState, TrustCertificate } from "@/lib/api/gateway";

export const credentialLabels: Record<CredentialSource, string> = {
  company: "Company credential",
  caller_supplied: "Personal credential",
  none: "No provider credential",
};

/** A previously fetched observation cannot remain healthy after its validity window. */
export function observationsCurrent(view: GatewayView, now: number): boolean {
  const { catalog, status } = view;
  return status.state === "current" && status.catalog_revision === catalog.catalog_revision &&
    status.applied_policy_revision === catalog.policy_revision &&
    status.observed_at !== null && status.valid_until !== null &&
    Date.parse(status.observed_at) <= now && now < Date.parse(status.valid_until);
}

export function observedHealth(
  view: GatewayView, kind: "endpoints" | "profiles", id: string, now: number,
): HealthState {
  if (!observationsCurrent(view, now)) return "unknown";
  if (kind === "profiles") {
    const desired = view.catalog.profiles.find((item) => item.id === id);
    const observed = view.status.profiles.find((item) => item.id === id);
    return desired && observed?.revision === desired.revision ? observed.state : "unknown";
  }
  return view.status.endpoints.find((item) => item.id === id)?.state ?? "unknown";
}

export function certificateValidity(certificate: TrustCertificate, now: number): string {
  const start = Date.parse(certificate.not_before);
  const end = Date.parse(certificate.not_after);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return "Validity unknown";
  if (now < start) return "Not yet valid";
  return now < end ? "Within validity dates" : "Expired";
}
