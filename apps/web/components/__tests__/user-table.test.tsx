import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { KeycloakUser, RecentSignin } from "@/lib/api/admin";
import { UserTable } from "../user-table";

const user: KeycloakUser = {
  id: "a",
  username: "alice",
  email: "alice@example.com",
  firstName: "Alice",
  lastName: "Example",
  enabled: true,
  emailVerified: true,
  createdTimestamp: 0,
};

describe("user status and sign-ins", () => {
  it.each([
    [true, true, "Enabled", "Email verified"],
    [true, false, "Enabled", "Email unverified"],
    [false, true, "Disabled", "Email verified"],
    [false, false, "Disabled", "Email unverified"],
    [null, null, "Account status unknown", "Email verification unknown"],
  ])("separates enabled=%s and verified=%s", (enabled, emailVerified, account, email) => {
    render(
      <UserTable users={[{ ...user, enabled, emailVerified }]} loading={false} error={null} />,
    );
    expect(screen.getByText(account)).toBeInTheDocument();
    const badge = screen.getByText(email);
    expect(badge).toBeInTheDocument();
    if (emailVerified === false) expect(badge).toHaveClass("bg-amber-100");
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });

  it("does not claim verification for a missing email", () => {
    render(<UserTable users={[{ ...user, email: null }]} loading={false} error={null} />);
    expect(screen.getByText("No email")).toBeInTheDocument();
    expect(screen.queryByText("Email verified")).not.toBeInTheDocument();
  });

  it.each<[RecentSignin, string]>([
    [{ status: "no_record", timestamp: null }, "No record in last 7 days"],
    [{ status: "unavailable", timestamp: null }, "Unavailable"],
    [{ status: "recorded", timestamp: "invalid" }, "Unavailable"],
  ])("preserves users for %s", (record, text) => {
    render(
      <UserTable
        users={[user]}
        loading={false}
        error={null}
        activity={{
          window_start: "2026-09-04T12:00:00Z",
          window_end: "2026-09-11T12:00:00Z",
          users: { a: record },
        }}
      />,
    );
    expect(screen.getByRole("link", { name: "alice" })).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("provides relative and accessible exact UTC time", () => {
    render(
      <UserTable
        users={[user]}
        loading={false}
        error={null}
        activity={{
          window_start: "2026-09-04T12:00:00Z",
          window_end: "2026-09-11T12:00:00Z",
          users: { a: { status: "recorded", timestamp: "2026-09-11T12:00:00+02:00" } },
        }}
      />,
    );
    const time = screen.getByLabelText("2 hours ago; 2026-09-11 10:00:00.000 UTC");
    expect(time).toHaveTextContent("2 hours ago");
    expect(time).toHaveAttribute("datetime", "2026-09-11T10:00:00.000Z");
    expect(time).toHaveAttribute("title", "2026-09-11 10:00:00.000 UTC");
  });
});
