import assert from "node:assert/strict";
import { test } from "node:test";
import type { GatewayView, TrustCertificate } from "../lib/api/gateway";
import { certificateValidity, observationsCurrent, observedHealth } from "../lib/gateway-view.ts";
import { usageSummary } from "../lib/usage-dashboard.ts";
import type { UserDailyUsage } from "../lib/api/usage";

const now = Date.parse("2026-10-14T12:00:00Z");
function view(): GatewayView {
  return {
    catalog: { schema_version: 1, catalog_revision: "catalog", policy_revision: "policy",
      endpoints: [], destinations: [], profiles: [{ id: "profile", revision: "new", limitations: [], operations: [] }] },
    status: { state: "current", reason: null, catalog_revision: "catalog", applied_policy_revision: "policy",
      observed_at: "2026-10-14T11:59:00Z", valid_until: "2026-10-14T12:01:00Z",
      endpoints: [{ id: "api", state: "available" }], profiles: [{ id: "profile", revision: "new", state: "available" }] },
  };
}

void test("health expires in an open page and never follows desired configuration or a mismatched revision", () => {
  const data = view();
  assert.equal(observedHealth(data, "endpoints", "api", now), "available");
  assert.equal(observedHealth(data, "endpoints", "missing", now), "unknown");
  assert.equal(observationsCurrent(data, now + 60_000), false);
  assert.equal(observedHealth(data, "endpoints", "api", now + 60_000), "unknown");
  assert.equal(observedHealth(data, "profiles", "profile", now), "available");
  const profile = data.catalog.profiles[0];
  assert.ok(profile);
  profile.revision = "next";
  assert.equal(observedHealth(data, "profiles", "profile", now), "unknown");
  data.status.applied_policy_revision = "old";
  assert.equal(observedHealth(data, "endpoints", "api", now), "unknown");
  data.status.applied_policy_revision = "policy";
  data.status.observed_at = "2026-10-15T12:00:00Z";
  assert.equal(observedHealth(data, "endpoints", "api", now), "unknown");
});

void test("trust publication and active state do not hide expired or invalid certificate dates", () => {
  const root: TrustCertificate = { fingerprint_sha256: "a".repeat(64), purpose: "inspection-root", state: "active",
    not_before: "2026-10-14T11:00:00Z", not_after: "2026-10-14T13:00:00Z" };
  assert.equal(certificateValidity(root, now), "Within validity dates");
  assert.equal(certificateValidity(root, now + 3_600_000), "Expired");
  assert.equal(certificateValidity(root, now - 3_600_001), "Not yet valid");
  assert.equal(certificateValidity({ ...root, not_after: "invalid" }, now), "Validity unknown");
});

void test("usage rollups preserve partial evidence and older responses never imply free usage", () => {
  const metric = { state: "known" as const, reported_sum: 0, complete_total: 0, known_records: 2, total_records: 2 };
  const usage: UserDailyUsage = {
    timezone: "UTC", start_date: "2026-10-01", end_date: "2026-10-02", today: "2026-10-14",
    days: [
      { date: "2026-10-01", models: [{ model: "example", requests: 2, total_tokens: 0, cost_usd: 0,
        accounting: { tokens: { ...metric }, cost_usd: { ...metric } } }] },
      { date: "2026-10-02", models: [{ model: "example", requests: 1, total_tokens: 8, cost_usd: 0.25 }] },
    ],
  };
  const result = usageSummary(usage);
  assert.equal(result.totals.requests, 3);
  assert.equal(result.totals.accounting.tokens.state, "partial");
  assert.equal(result.totals.accounting.tokens.complete_total, null);
  assert.equal(result.totals.accounting.tokens.reported_sum, 8);
  assert.equal(result.models[0]?.accounting.cost_usd.state, "partial");
  assert.equal(result.daily[0]?.accounting.cost_usd.complete_total, 0);
  assert.equal(result.daily[1]?.accounting.cost_usd.state, "unknown");
  assert.equal(result.daily[1].accounting.cost_usd.complete_total, null);
});
