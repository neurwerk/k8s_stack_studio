import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PolicyEnginePage from "./page";
import type { ConfigState } from "@/lib/config-generator";
import type { EvaluateResponse } from "@/lib/api/policy-engine";

const api = vi.hoisted(() => ({ policyEngineEvaluate: vi.fn() }));

vi.mock("@/lib/api/policy-engine", () => ({
  policyEngineEvaluate: api.policyEngineEvaluate,
}));
vi.mock("@/lib/auth/roles", () => ({ useIsPiiAdmin: () => true }));
vi.mock("@/components/actions-reference", () => ({ ActionsReference: () => null }));
vi.mock("@/components/config-preview", () => ({ ConfigPreview: () => null }));
vi.mock("@/components/config-panel", () => ({
  ConfigPanel: ({
    state,
    onChange,
  }: {
    state: ConfigState;
    onChange: (state: ConfigState) => void;
  }) => (
    <button
      type="button"
      onClick={() => {
        onChange({
          ...state,
          piiEngine: {
            ...state.piiEngine,
            pii: { ...state.piiEngine.pii, scoreThreshold: 0.91 },
          },
        });
      }}
    >
      Change policy config
    </button>
  ),
}));

const invalidResult: EvaluateResponse = {
  api_version: "v1",
  valid: false,
  issues: [
    {
      stage: "schema",
      path: ["pii", "defaultAction"],
      code: "invalid_action",
      message: "Action is invalid.",
    },
  ],
  issues_truncated: false,
};

describe("PolicyEnginePage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.policyEngineEvaluate.mockResolvedValue(invalidResult);
  });

  it("uses only evaluate and sends the current request with an optional draft", async () => {
    const user = userEvent.setup();
    render(<PolicyEnginePage />);

    expect(screen.queryByText(/Simulation only - no model is called/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Evaluate policy" }));
    await screen.findByText("Policy candidate is invalid");

    expect(api.policyEngineEvaluate).toHaveBeenLastCalledWith(
      {
        model: "studio-policy-test",
        messages: [
          {
            role: "user",
            content:
              "Hello John Doe, my AWS key is AKIAIOSFODNN7EXAMPLE and my email is john@example.com",
          },
        ],
      },
      undefined,
    );

    await user.click(screen.getByRole("checkbox", { name: /draft policy/i }));
    expect(screen.queryByText("Policy candidate is invalid")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Evaluate policy" }));
    await screen.findByText("Policy candidate is invalid");

    const policy = api.policyEngineEvaluate.mock.calls.at(-1)?.[1] as Record<string, unknown>;
    expect(policy).toBeDefined();
    expect(policy).toHaveProperty("pii");
    expect(screen.queryByText(/AgentGateway model test/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run test/i })).not.toBeInTheDocument();
  });

  it("clears results when text, draft selection, or policy config changes", async () => {
    const user = userEvent.setup();
    render(<PolicyEnginePage />);
    const evaluate = screen.getByRole("button", { name: "Evaluate policy" });

    await user.click(evaluate);
    await screen.findByText("Policy candidate is invalid");
    await user.type(screen.getByLabelText("Test Text"), " changed");
    expect(screen.queryByText("Policy candidate is invalid")).not.toBeInTheDocument();

    await user.click(evaluate);
    await screen.findByText("Policy candidate is invalid");
    await user.click(screen.getByRole("checkbox", { name: /draft policy/i }));
    expect(screen.queryByText("Policy candidate is invalid")).not.toBeInTheDocument();

    await user.click(evaluate);
    await screen.findByText("Policy candidate is invalid");
    await user.click(screen.getByRole("button", { name: "Configure Policy" }));
    await user.click(screen.getByRole("button", { name: "Change policy config" }));
    expect(screen.queryByText("Policy candidate is invalid")).not.toBeInTheDocument();
  });

  it("ignores an in-flight response after its input becomes stale", async () => {
    let resolveEvaluation: (value: EvaluateResponse) => void = () => undefined;
    api.policyEngineEvaluate.mockReturnValueOnce(
      new Promise<EvaluateResponse>((resolve) => {
        resolveEvaluation = resolve;
      }),
    );
    const user = userEvent.setup();
    render(<PolicyEnginePage />);

    await user.click(screen.getByRole("button", { name: "Evaluate policy" }));
    expect(screen.getByRole("status")).toHaveTextContent("Evaluating policy without calling a model");
    await user.type(screen.getByLabelText("Test Text"), " newer");
    resolveEvaluation(invalidResult);

    await waitFor(() => {
      expect(screen.queryByText("Policy candidate is invalid")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Evaluating policy without calling a model")).not.toBeInTheDocument();
  });
});
