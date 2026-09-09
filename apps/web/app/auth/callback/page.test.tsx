import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthCallback from "./page";

const { replace, auth } = vi.hoisted<{
  replace: ReturnType<typeof vi.fn>;
  auth: {
    isLoading: boolean;
    isAuthenticated: boolean;
    error: Error | undefined;
    user: { state: unknown };
  };
}>(() => ({
  replace: vi.fn(),
  auth: {
    isLoading: false,
    isAuthenticated: true,
    error: undefined,
    user: { state: undefined },
  },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("react-oidc-context", () => ({ useAuth: () => auth }));

describe("AuthCallback", () => {
  beforeEach(() => {
    replace.mockClear();
    auth.isLoading = false;
    auth.isAuthenticated = true;
    auth.error = undefined;
    auth.user.state = undefined;
  });

  it.each([
    "/",
    "/users/other-user?tab=usage&days=7#daily",
    "/policy-engine?mode=test#results",
    "/users/user%20one?next=https%3A%2F%2Fexample.com#usage",
  ])("preserves the explicit local return path %s", (returnTo) => {
    auth.user.state = { returnTo };
    render(<AuthCallback />);
    expect(replace).toHaveBeenCalledWith(returnTo);
  });

  it.each([
    undefined,
    null,
    "invalid",
    [],
    {},
    { returnTo: 42 },
    { returnTo: "" },
    { returnTo: "users/self" },
    { returnTo: "https://evil.example/users" },
    { returnTo: `${window.location.origin}/users/self` },
    { returnTo: "//evil.example/users" },
    { returnTo: "/\\evil.example" },
    { returnTo: "/%5cevil.example" },
    { returnTo: "/%2f%2fevil.example" },
    { returnTo: "/\n/evil.example" },
    { returnTo: "javascript:alert(1)" },
    { returnTo: "/auth/callback?code=old#state" },
    { returnTo: "/auth/callback/child" },
    { returnTo: "/auth//callback" },
    { returnTo: "/users/../auth/callback" },
    { returnTo: "/auth/%63allback" },
    { returnTo: "/auth%2fcallback/child" },
    { returnTo: "/auth/callback/%2e%2e/callback" },
    { returnTo: "/users/%ZZ" },
  ])("falls back to root for unsafe or malformed state %j", (state) => {
    auth.user.state = state;
    render(<AuthCallback />);
    expect(replace).toHaveBeenCalledWith("/");
  });

  it.each(["loading", "unauthenticated", "error"])("does not navigate while %s", (status) => {
    auth.isLoading = status === "loading";
    auth.isAuthenticated = status !== "unauthenticated";
    auth.error = status === "error" ? new Error("Sign-in failed") : undefined;
    render(<AuthCallback />);
    expect(replace).not.toHaveBeenCalled();
  });
});
