import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UserDetailPage from "./page";

const mocks = vi.hoisted(() => ({
  fetchUser: vi.fn(),
  fetchUserAccess: vi.fn(),
  fetchOwnGroups: vi.fn(),
  roles: {
    currentUserId: "viewer-user",
    isApiKeyAdmin: false,
    isKeycloakAdmin: false,
    ownRoles: ["studio-user", "default-roles-studio", "offline_access"],
  },
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ user_id: "target-user" }) }));
vi.mock("@/lib/api/admin", () => ({
  fetchUser: mocks.fetchUser, fetchUserAccess: mocks.fetchUserAccess,
  fetchOwnGroups: mocks.fetchOwnGroups,
}));
vi.mock("@/lib/auth/roles", () => ({
  useCurrentUserId: () => mocks.roles.currentUserId,
  useIsApiKeyAdmin: () => mocks.roles.isApiKeyAdmin,
  useIsKeycloakAdmin: () => mocks.roles.isKeycloakAdmin,
  useUserRoles: () => mocks.roles.ownRoles,
}));
vi.mock("@/components/api-key-manager", () => ({
  ApiKeyManager: () => <p>API key manager</p>,
}));
vi.mock("@/components/user-access", () => ({
  UserAccess: ({ groups }: { groups?: { name: string }[] }) => (
    <p>Groups: {groups?.map((group) => group.name).join(", ")}</p>
  ),
}));

describe("UserDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.roles.currentUserId = "viewer-user";
    mocks.roles.isApiKeyAdmin = false;
    mocks.roles.isKeycloakAdmin = false;
    mocks.fetchUserAccess.mockResolvedValue({
      groups: [], groups_truncated: false,
      direct: { realm_roles: [], clients: [] },
      effective_realm_roles: [
        { id: "role-1", name: "pii-admin", description: "", composite: false },
        { id: "role-2", name: "default-roles-studio", description: "", composite: true },
        { id: "role-3", name: "studio-user", description: "", composite: false },
      ],
    });
    mocks.fetchOwnGroups.mockResolvedValue({ groups: [], groups_truncated: false });
  });

  it("rejects cross-user profile views without Keycloak or API key administration", () => {
    render(<UserDetailPage />);

    expect(screen.getByText("Access Denied")).toBeInTheDocument();
    expect(screen.queryByText("API key manager")).not.toBeInTheDocument();
    expect(mocks.fetchUser).not.toHaveBeenCalled();
  });

  it("shows assigned roles in the profile card without usage", async () => {
    mocks.roles.isKeycloakAdmin = true;
    mocks.fetchUser.mockResolvedValue({
      id: "target-user", username: "target", firstName: "Target", lastName: "User",
      createdTimestamp: 0,
    });

    render(<UserDetailPage />);

    expect(await screen.findByText("pii-admin")).toBeInTheDocument();
    expect(screen.getByText("studio-user")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Target User" })).toBeInTheDocument();
    expect(screen.getByText("Roles")).toBeInTheDocument();
    expect(screen.queryByText("default-roles-studio")).not.toBeInTheDocument();
    expect(screen.queryByText("User usage")).not.toBeInTheDocument();
  });

  it("shows memberships for admin views and verified roles on the user's own profile", async () => {
    mocks.roles.isKeycloakAdmin = true;
    mocks.roles.currentUserId = "target-user";
    mocks.fetchUser.mockResolvedValue({
      id: "target-user", username: "target", firstName: "Target", lastName: "User",
      createdTimestamp: 0,
    });
    mocks.fetchUserAccess.mockResolvedValue({
      groups: [{ id: "group-1", name: "Engineering", path: "/Engineering", subgroup_count: 0 }],
      groups_truncated: false,
      direct: { realm_roles: [], clients: [] }, effective_realm_roles: [],
    });

    render(<UserDetailPage />);

    expect(await screen.findByText("Groups: Engineering")).toBeInTheDocument();
    expect(screen.getByText("studio-user")).toBeInTheDocument();
    expect(screen.queryByText("offline_access")).not.toBeInTheDocument();
  });

  it("shows a regular user's verified roles without requesting admin access", async () => {
    mocks.roles.currentUserId = "target-user";
    mocks.fetchUser.mockResolvedValue({
      id: "target-user", username: "target", firstName: "Target", lastName: "User",
      createdTimestamp: 0,
    });

    render(<UserDetailPage />);

    expect(await screen.findByRole("heading", { name: "Target User" })).toBeInTheDocument();
    expect(screen.getByText("studio-user")).toBeInTheDocument();
    expect(mocks.fetchUserAccess).not.toHaveBeenCalled();
  });

  it("shows a profile error instead of usage when loading fails", async () => {
    mocks.roles.isKeycloakAdmin = true;
    mocks.fetchUser.mockRejectedValue(new Error("profile unavailable"));

    render(<UserDetailPage />);

    expect(await screen.findByText("Unable to load the user profile. Please try again."))
      .toBeInTheDocument();
    expect(screen.queryByText("Groups: Engineering")).not.toBeInTheDocument();
  });
});
