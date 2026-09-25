import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "../sidebar";

const state = vi.hoisted(() => ({
  pathname: "/usage",
  roles: [] as string[],
  signoutRedirect: vi.fn(),
}));

vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ signoutRedirect: state.signoutRedirect }),
}));
vi.mock("@/lib/auth/roles", () => ({
  useCurrentUserId: () => "user-1",
  useIsKeycloakAdmin: () => state.roles.includes("keycloak-admin"),
  useIsOpensearchAdmin: () => state.roles.includes("opensearch-admin"),
  useIsPiiAdmin: () => state.roles.includes("pii-admin"),
}));
vi.mock("@/lib/api/version", () => ({ fetchVersion: () => Promise.resolve(null) }));

describe("Sidebar settings", () => {
  beforeEach(() => {
    state.pathname = "/usage";
    state.roles = [];
    state.signoutRedirect.mockClear();
  });

  it("shows profile and logout, but hides configuration without the PII role", async () => {
    render(<Sidebar />);

    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Profile" })).toHaveAttribute("href", "/users/user-1");
    expect(screen.queryByRole("button", { name: "Configuration" })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Logout" }));
    expect(state.signoutRedirect).toHaveBeenCalledOnce();
  });

  it("expands the role-gated PII Policy submenu, including from a collapsed sidebar", async () => {
    state.roles = ["pii-admin"];
    const user = userEvent.setup();
    render(<Sidebar />);

    const configuration = screen.getByRole("button", { name: "Configuration" });
    expect(configuration).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "PII Policy" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    await user.click(configuration);
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeInTheDocument();
    expect(configuration).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "PII Policy" })).toHaveAttribute(
      "href",
      "/policy-engine",
    );
  });

  it("opens Configuration on the PII Policy page", () => {
    state.roles = ["pii-admin"];
    state.pathname = "/policy-engine";
    render(<Sidebar />);

    expect(screen.getByRole("button", { name: "Configuration" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("link", { name: "PII Policy" })).toBeInTheDocument();
  });

  it("shows a future API Keys item to non-admins and role-gates admin links", () => {
    const { rerender } = render(<Sidebar />);
    expect(screen.getByText("API Keys").closest("[aria-disabled]")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.queryByRole("link", { name: "API Keys" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Groups and Roles" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Logs" })).not.toBeInTheDocument();

    state.roles = ["opensearch-admin"];
    rerender(<Sidebar />);
    expect(screen.getByRole("link", { name: "Logs" })).toHaveAttribute("href", "/logs");
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Groups and Roles" })).not.toBeInTheDocument();

    state.roles = ["keycloak-admin"];
    rerender(<Sidebar />);
    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/users");
    expect(screen.queryByRole("link", { name: "Groups and Roles" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Groups" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Realm Roles" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Clients" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Logs" })).not.toBeInTheDocument();

    state.roles = ["keycloak-admin", "opensearch-admin"];
    rerender(<Sidebar />);
    const items = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(items.slice(0, 3)).toEqual(["/usage", "/users", "/logs"]);
  });
});
