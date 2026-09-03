import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UserDetailPage from "./page";

const mocks = vi.hoisted(() => ({
  fetchUser: vi.fn(),
  roles: {
    currentUserId: "viewer-user",
    isApiKeyAdmin: false,
    isKeycloakAdmin: false,
    isUsageAdmin: true,
  },
}));

vi.mock("next/navigation", () => ({ useParams: () => ({ user_id: "target-user" }) }));
vi.mock("@/lib/api/admin", () => ({ fetchUser: mocks.fetchUser }));
vi.mock("@/lib/auth/roles", () => ({
  useCurrentUserId: () => mocks.roles.currentUserId,
  useHasRole: (role: string) => role === "langfuse-admin" && mocks.roles.isUsageAdmin,
  useIsApiKeyAdmin: () => mocks.roles.isApiKeyAdmin,
  useIsKeycloakAdmin: () => mocks.roles.isKeycloakAdmin,
}));
vi.mock("@/components/api-key-manager", () => ({
  ApiKeyManager: () => <p>API key manager</p>,
}));
vi.mock("@/components/user-usage", () => ({
  UserUsage: ({ userId }: { userId: string }) => <p>Usage for {userId}</p>,
}));

describe("UserDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.roles.currentUserId = "viewer-user";
    mocks.roles.isApiKeyAdmin = false;
    mocks.roles.isKeycloakAdmin = false;
    mocks.roles.isUsageAdmin = true;
  });

  it("renders authorized cross-user usage without profile access", () => {
    render(<UserDetailPage />);

    expect(screen.getByText("Usage for target-user")).toBeInTheDocument();
    expect(screen.queryByText("Access Denied")).not.toBeInTheDocument();
    expect(screen.queryByText("API key manager")).not.toBeInTheDocument();
    expect(mocks.fetchUser).not.toHaveBeenCalled();
  });

  it("keeps authorized usage available when profile loading fails", async () => {
    mocks.roles.isKeycloakAdmin = true;
    mocks.fetchUser.mockRejectedValue(new Error("profile unavailable"));

    render(<UserDetailPage />);

    expect(await screen.findByText("Usage for target-user")).toBeInTheDocument();
    expect(screen.queryByText("Unable to load the user profile. Please try again.")).not.toBeInTheDocument();
  });
});
