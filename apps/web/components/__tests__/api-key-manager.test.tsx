import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiKeyManager } from "../api-key-manager";

const api = vi.hoisted(() => ({
  createApiKey: vi.fn(),
  fetchAgentGatewayPermissions: vi.fn(),
  fetchApiKeys: vi.fn(),
  revokeApiKey: vi.fn(),
}));

vi.mock("@/lib/api/admin", () => api);

const listedKey = {
  id: "key-1",
  key_prefix: "ak_test",
  name: "automation",
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-04-01T00:00:00Z",
  permissions: ["llm:invoke", "model:example:invoke"],
  revoked: false,
};

describe("ApiKeyManager", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.fetchApiKeys.mockResolvedValue([listedKey]);
    api.fetchAgentGatewayPermissions.mockResolvedValue(["llm:invoke", "model:example:invoke"]);
    api.createApiKey.mockResolvedValue({
      id: "key-2",
      api_key: "secret-value",
      key_prefix: "secret-v",
      permissions: ["llm:invoke"],
    });
  });

  it("requires a selected permission and valid expiry before creating an immutable key", async () => {
    const user = userEvent.setup();
    render(<ApiKeyManager userId="target-user" canManage />);

    expect(await screen.findByText("automation")).toBeInTheDocument();
    expect(screen.getByText("llm:invoke, model:example:invoke")).toBeInTheDocument();
    expect(screen.queryByText(/renew/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create API key" }));
    expect(await screen.findByText(/Permissions and expiry are immutable/)).toBeInTheDocument();
    expect(api.fetchAgentGatewayPermissions).toHaveBeenCalledWith("target-user");

    const submit = screen.getByRole("button", { name: "Create key" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Key name"), "cli");
    await user.clear(screen.getByLabelText("Expiry (days)"));
    await user.type(screen.getByLabelText("Expiry (days)"), "0");
    expect(submit).toBeDisabled();

    await user.clear(screen.getByLabelText("Expiry (days)"));
    await user.type(screen.getByLabelText("Expiry (days)"), "30");
    await user.click(screen.getByRole("checkbox", { name: "llm:invoke" }));
    await user.click(submit);

    await waitFor(() => {
      expect(api.createApiKey).toHaveBeenCalledWith("target-user", {
        name: "cli",
        permissions: ["llm:invoke"],
        expires_in_days: 30,
      });
    });
    expect(await screen.findByText("secret-value")).toBeInTheDocument();
    expect(screen.getByText("Expires in 30 days.")).toBeInTheDocument();
  });

  it("does not create a key when the name contains spaces", async () => {
    const user = userEvent.setup();
    render(<ApiKeyManager userId="target-user" canManage />);

    await screen.findByText("automation");
    await user.click(screen.getByRole("button", { name: "Create API key" }));
    await user.type(screen.getByLabelText("Key name"), "deployment cli");
    await user.click(await screen.findByRole("checkbox", { name: "llm:invoke" }));

    const submit = screen.getByRole("button", { name: "Create key" });
    expect(screen.getByLabelText("Key name")).toHaveAttribute("aria-invalid", "true");
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(api.createApiKey).not.toHaveBeenCalled();
  });

  it("renders a retryable permissions failure without exposing a server error", async () => {
    const user = userEvent.setup();
    api.fetchAgentGatewayPermissions.mockRejectedValue(new Error("token=secret"));
    render(<ApiKeyManager userId="target-user" canManage />);

    await screen.findByText("automation");
    await user.click(screen.getByRole("button", { name: "Create API key" }));

    expect(
      await screen.findByText("Unable to load available permissions. Please try again."),
    ).toBeInTheDocument();
    expect(screen.queryByText("token=secret")).not.toBeInTheDocument();
  });
});
