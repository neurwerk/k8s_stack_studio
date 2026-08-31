/** Tests for the PII Engine configuration generator. */

import { describe, expect, it } from "vitest";

import {
  PRESET_ENTITIES,
  createDefaultState,
  generateYaml,
  toPolicyOverride,
} from "../config-generator";
import { FALLBACK_ACTIONS } from "../actions-fallback";

describe("PII Engine configuration", () => {
  it("uses engine terminology in generated YAML", () => {
    const yaml = generateYaml(createDefaultState());
    expect(yaml).toContain("monitorPiiEngine:");
    expect(yaml).toContain("  policy:");
    expect(yaml).toContain("    defaultOperator:");
    expect(yaml).toContain("      analyzerEntities: []");
    expect(yaml).toContain("      hashWindowHours: 24");
    expect(yaml).toContain("    routing:");
    expect(yaml).not.toContain("monitorPresidioAnalyzer");
    expect(yaml).not.toContain("monitorAgentgatewayExtproc");
  });

  it("keeps safe defaults when policy metadata is incomplete", () => {
    const state = createDefaultState();
    expect(state.piiEngine.pii.defaultAction).toBe("block");
    expect(state.piiEngine.pii.entityPolicies.length).toBeGreaterThan(0);
  });

  it("offers the engine-owned Steuernummer entity", () => {
    expect(PRESET_ENTITIES).toContain("STEUERNUMMER");
  });

  it("keeps the complete fallback action set", () => {
    expect(FALLBACK_ACTIONS).toHaveLength(9);
    expect(
      FALLBACK_ACTIONS.find((action) => action.name === "reversible_replace")?.reversible,
    ).toBe(true);
    expect(FALLBACK_ACTIONS.find((action) => action.name === "hash")?.params[0]?.options).toEqual([
      "sha256",
    ]);
    expect(FALLBACK_ACTIONS.find((action) => action.name === "encrypt")?.params).toEqual([]);
  });

  it("sends typed action parameters without key material", () => {
    const state = createDefaultState();
    state.piiEngine.pii.entityPolicies = [
      {
        entityType: "EMAIL_ADDRESS",
        action: "mask",
        params: { masking_char: "#", chars_to_mask: "8", from_end: "false", key: "never" },
        patterns: [],
      },
    ];
    const override = toPolicyOverride(state.piiEngine);
    const pii = override.pii as { entityPolicies: Record<string, unknown>[] };
    expect(pii.entityPolicies[0]).toMatchObject({ chars_to_mask: 8, from_end: false });
    expect(pii.entityPolicies[0]).not.toHaveProperty("key");
  });
});
