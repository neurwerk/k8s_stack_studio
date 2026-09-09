import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VerifiedSessionProvider } from "@/lib/auth/session-context";
import Home from "./page";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

function landing(subject: string) {
  return (
    <VerifiedSessionProvider
      session={{ subject, realm_roles: ["studio-user"], agentgateway_roles: [] }}
    >
      <Home />
    </VerifiedSessionProvider>
  );
}

describe("Home", () => {
  beforeEach(() => replace.mockClear());

  it("replaces root with the verified user's encoded profile without specialty roles", async () => {
    render(landing("user/one?#"));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith("/users/user%2Fone%3F%23");
    });
  });

  it("waits for a missing user ID rather than selecting another landing page", async () => {
    const { rerender } = render(landing(""));

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(replace).not.toHaveBeenCalled();

    rerender(landing("user-1"));
    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith("/users/user-1");
    });
  });
});
