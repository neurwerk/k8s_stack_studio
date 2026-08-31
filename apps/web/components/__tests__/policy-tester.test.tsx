import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  PII_GUARD_INSTRUCTION,
  PolicyTester,
  TEST_TEMPLATES,
  buildModelVisibleRequest,
  codePointToUtf16Offset,
  getTemplateGroups,
} from "../policy-tester";
import type { EvaluateResponse, SupportedRequest } from "@/lib/api/policy-engine";

const request: SupportedRequest = {
  model: "studio-policy-test",
  messages: [{ role: "user", content: "A😀BCDEF" }],
};

const validResult: Extract<EvaluateResponse, { valid: true }> = {
  api_version: "v1",
  valid: true,
  issues: [],
  issues_truncated: false,
  decision: "apply_actions",
  entities: ["EMAIL_ADDRESS", "PHONE_NUMBER"],
  entity_counts: { EMAIL_ADDRESS: 1, PHONE_NUMBER: 1 },
  applied_actions: ["redact"],
  remote_allowed: true,
  route_class: "local-sensitive",
  request: { model: "studio-policy-test", messages: [{ role: "user", content: "AF" }] },
  analysis: {
    source: "current_request",
    scan_performed: true,
    duration_ms: 37,
    overlap_count: 1,
    overlap_resolution: "strictest_action",
    policy_version: "candidate-1",
    text_leaf_count: 1,
    cached_decision_applied: false,
  },
  notices: { request: ["Request notice"], response: ["Response notice"] },
  safety_rule: null,
  report: {
    rows: [
      {
        entity_type: "EMAIL_ADDRESS",
        action: "mask",
        detected_count: 1,
        transformed_count: 0,
        unique_transformed_count: 0,
      },
      {
        entity_type: "PHONE_NUMBER",
        action: "redact",
        detected_count: 1,
        transformed_count: 1,
        unique_transformed_count: 1,
      },
    ],
  },
  diagnostics: {
    logical_detections: [
      {
        path: ["messages", 0, "content"],
        start: 1,
        end: 4,
        entity_type: "EMAIL_ADDRESS",
        score: 0.8,
        source: "deterministic",
        configured_action: "mask",
        resolved_action: "redact",
      },
      {
        path: ["messages", 0, "content"],
        start: 3,
        end: 6,
        entity_type: "PHONE_NUMBER",
        score: 0.9,
        source: "spacy",
        configured_action: "redact",
        resolved_action: "redact",
      },
    ],
    effective_regions: [
      {
        path: ["messages", 0, "content"],
        start: 1,
        end: 6,
        entity_type: "PHONE_NUMBER",
        action: "redact",
        source: "spacy",
        score: 0.9,
        member_entity_types: ["EMAIL_ADDRESS", "PHONE_NUMBER"],
        overlap: true,
      },
    ],
    truncated: false,
  },
  simulation: {
    type: "deterministic_echo",
    status: "completed",
    reason: null,
    model_called: false,
    model_response: "[SIMULATED - NO MODEL CALLED]\nAF <REV_EMAIL>",
    user_response: "[SIMULATED - NO MODEL CALLED]\nAF restored@example.com",
    restored_entity_counts: { EMAIL_ADDRESS: 1 },
  },
};

const expectedTemplates = [
  "Trigger All - Safety + PII",
  "Prompt Injection",
  "Jailbreak",
  "System Prompt Extraction",
  "Harmful Content",
  "Encoding Evasion",
  "Self Harm",
  "AWS Key Leak",
  "API Token in Text",
  "Password in Prose",
  "Personal Info",
  "Credit Card",
  "US SSN",
  "Multiple PII Entities",
  "German Steuernummer",
];

describe("PolicyTester", () => {
  it("retains the complete security and PII sample catalog", () => {
    expect(Object.keys(TEST_TEMPLATES)).toEqual(expectedTemplates);
    expect(TEST_TEMPLATES["German Steuernummer"]?.text).toContain("289/123/45678");
    expect(getTemplateGroups()).toEqual([
      { group: "Security Tests", keys: expectedTemplates.slice(0, 10) },
      { group: "PII Examples", keys: expectedTemplates.slice(10) },
    ]);
  });

  it("converts code-point offsets without splitting astral characters", () => {
    expect(codePointToUtf16Offset("A😀BC", 1)).toBe(1);
    expect(codePointToUtf16Offset("A😀BC", 2)).toBe(3);

    render(<PolicyTester request={request} result={validResult} />);

    const original = screen.getByLabelText("Original findings at $.messages[0].content");
    const marks = original.querySelectorAll("mark");
    expect(marks[0]).toHaveTextContent("😀B");
    expect(original.querySelector('[data-overlap-depth="2"]')).toHaveTextContent("C");
    expect(original).toHaveTextContent("A😀BCDEF");
  });

  it("shows rich findings, effective overlap winners, timing, and policy metadata", () => {
    render(<PolicyTester request={request} result={validResult} />);

    expect(screen.getByText(/duration_ms:/)).toHaveTextContent("37 ms");
    expect(screen.getByText(/Overlaps:/)).toHaveTextContent("1");
    expect(screen.getByText(/Text leaves:/)).toHaveTextContent("1");
    expect(screen.getByText(/policy candidate-1/)).toBeInTheDocument();
    expect(screen.getByText(/Route:/)).toHaveTextContent("local-sensitive");
    expect(screen.getByText(/Request notices:/)).toHaveTextContent("Request notice");
    expect(screen.getByText(/Response notices:/)).toHaveTextContent("Response notice");

    const logicalTable = screen.getByRole("table", { name: "Logical detections" });
    expect(within(logicalTable).getByText("0.800")).toBeInTheDocument();
    expect(screen.getAllByText("deterministic").length).toBeGreaterThan(0);
    expect(screen.getAllByText("EMAIL_ADDRESS, PHONE_NUMBER").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Effective regions at $.messages[0].content")).toHaveTextContent(
      "A😀BCDEF",
    );
  });

  it("renders the transformed request with the exact leading extProc guard", () => {
    render(<PolicyTester request={request} result={validResult} />);

    expect(screen.getByText("What would be sent to the model")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(PII_GUARD_INSTRUCTION))).toBeInTheDocument();
    expect(screen.getByText(/"role": "system"/)).toBeInTheDocument();
    expect(screen.getByText(/"content": "AF"/)).toBeInTheDocument();
    expect(screen.queryByText("Deterministic response simulation")).not.toBeInTheDocument();
  });

  it("places the fixed guard in Chat and Responses requests like extProc", () => {
    expect(buildModelVisibleRequest(request)).toEqual({
      ...request,
      messages: [
        { role: "system", content: PII_GUARD_INSTRUCTION },
        ...request.messages,
      ],
    });
    expect(
      buildModelVisibleRequest({
        model: "studio-policy-test",
        input: "hello",
        instructions: "caller instructions",
      }),
    ).toEqual({
      model: "studio-policy-test",
      input: "hello",
      instructions: `${PII_GUARD_INSTRUCTION}\n\ncaller instructions`,
    });
    expect(buildModelVisibleRequest({ model: "studio-policy-test", input: "hello" })).toEqual({
      model: "studio-policy-test",
      input: "hello",
      instructions: PII_GUARD_INSTRUCTION,
    });
  });

  it("renders bounded invalid-candidate issues as a normal result", () => {
    const invalid: EvaluateResponse = {
      api_version: "v1",
      valid: false,
      issues: [
        {
          stage: "merge",
          path: ["pii", "entityPolicies", 0, "action"],
          code: "unsupported_action",
          message: "Action is not supported.",
        },
      ],
      issues_truncated: true,
    };

    render(<PolicyTester request={request} result={invalid} />);

    expect(screen.getByText("Policy candidate is invalid")).toBeInTheDocument();
    expect(screen.getByText("unsupported_action")).toBeInTheDocument();
    expect(screen.getByText("$.pii.entityPolicies[0].action")).toBeInTheDocument();
    expect(screen.getByText("Action is not supported.")).toBeInTheDocument();
    expect(screen.getByText(/Additional issues were truncated/)).toBeInTheDocument();
  });

  it("shows a blocked state without model output or live model controls", () => {
    const blocked: typeof validResult = {
      ...validResult,
      decision: "block",
      remote_allowed: false,
      request: null,
      simulation: {
        type: "deterministic_echo",
        status: "skipped",
        reason: "request_blocked",
        model_called: false,
        model_response: null,
        user_response: null,
        restored_entity_counts: {},
      },
    };

    render(<PolicyTester request={request} result={blocked} />);

    expect(screen.getByText("No request is forwarded for this decision.")).toBeInTheDocument();
    expect(screen.queryByText("Deterministic response simulation")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run test/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/authorized model/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/token usage/i)).not.toBeInTheDocument();
  });
});
