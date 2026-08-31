import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/lib/api/client";
import { useUserRoles } from "@/lib/auth/roles";
import { AuthGuard } from "../auth-guard";

interface AuthState {
  activeNavigator: string | undefined;
  error: undefined;
  isAuthenticated: boolean;
  isLoading: boolean;
  removeUser: ReturnType<typeof vi.fn>;
  signinRedirect: ReturnType<typeof vi.fn>;
  signoutRedirect: ReturnType<typeof vi.fn>;
  user: { access_token: string; profile: unknown } | undefined;
}

const fetchSession = vi.hoisted(() => vi.fn());

const authState: { current: AuthState } = vi.hoisted(() => ({
  current: {
    activeNavigator: undefined,
    error: undefined,
    isAuthenticated: false,
    isLoading: false,
    removeUser: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
    user: undefined,
  },
}));

vi.mock("react-oidc-context", () => ({
  useAuth: () => authState.current,
}));

vi.mock("@/lib/api/session", () => ({ fetchSession }));

function RoleProbe() {
  return <p>Roles: {useUserRoles().join(", ")}</p>;
}

describe("AuthGuard", () => {
  beforeEach(() => {
    fetchSession.mockReset();
    authState.current = {
      activeNavigator: undefined,
      error: undefined,
      isAuthenticated: false,
      isLoading: false,
      removeUser: vi.fn(),
      signinRedirect: vi.fn(),
      signoutRedirect: vi.fn(),
      user: undefined,
    };
  });

  it("admits roles returned from the verified API session", async () => {
    fetchSession.mockResolvedValue({
      subject: "user-1",
      realm_roles: ["pii-admin", "studio-user"],
      agentgateway_roles: ["llm:invoke"],
    });
    authState.current.isAuthenticated = true;
    authState.current.user = { access_token: "access-token", profile: { sub: "user-1" } };

    render(
      <AuthGuard>
        <RoleProbe />
      </AuthGuard>,
    );

    expect(await screen.findByText("Roles: pii-admin, studio-user")).toBeInTheDocument();
    expect(authState.current.signinRedirect).not.toHaveBeenCalled();
  });

  it("lets an authenticated but unadmitted user sign out", async () => {
    const user = userEvent.setup();
    fetchSession.mockRejectedValue(new ApiRequestError(403));
    authState.current.isAuthenticated = true;
    authState.current.user = { access_token: "access-token", profile: { sub: "user-1" } };

    render(
      <AuthGuard>
        <p>Studio content</p>
      </AuthGuard>,
    );

    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.queryByText("Studio content")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Log out and use another account" }));

    expect(authState.current.signoutRedirect).toHaveBeenCalledTimes(1);
  });

  it("removes an expired local session rejected by the API", async () => {
    fetchSession.mockRejectedValue(new ApiRequestError(401));
    authState.current.isAuthenticated = true;
    authState.current.user = { access_token: "expired-token", profile: { sub: "user-1" } };

    render(
      <AuthGuard>
        <p>Studio content</p>
      </AuthGuard>,
    );

    await waitFor(() => {
      expect(authState.current.removeUser).toHaveBeenCalledTimes(1);
    });
  });

  it("starts one redirect only for an unauthenticated caller", async () => {
    render(
      <AuthGuard>
        <p>Studio content</p>
      </AuthGuard>,
    );

    await waitFor(() => {
      expect(authState.current.signinRedirect).toHaveBeenCalledTimes(1);
    });
  });
});
