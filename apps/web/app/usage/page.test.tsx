import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import type * as Recharts from "recharts";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAllDailyUsage, fetchUsagePeople, fetchUserDailyUsage } from "@/lib/api/usage";
import { fetchUser } from "@/lib/api/admin";
import type { UserDailyUsage } from "@/lib/api/usage";
import UsagePage from "./page";

const viewer = vi.hoisted(() => ({ userId: "admin-id", isAdmin: true, canReadNames: true }));
vi.mock("@/lib/auth/roles", () => ({
  useCurrentUserId: () => viewer.userId,
  useHasRole: () => viewer.isAdmin,
  useIsKeycloakAdmin: () => viewer.canReadNames,
}));
vi.mock("@/lib/api/usage", () => ({
  fetchAllDailyUsage: vi.fn(), fetchUsagePeople: vi.fn(), fetchUserDailyUsage: vi.fn(),
}));
vi.mock("@/lib/api/admin", () => ({ fetchUser: vi.fn() }));
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof Recharts>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <actual.ResponsiveContainer width={600} height={280}>{children}</actual.ResponsiveContainer>
    ),
  };
});

function usage(start: string): UserDailyUsage {
  return {
    timezone: "Europe/Berlin", start_date: start, end_date: "2026-09-18", today: "2026-09-18",
    days: [
      { date: "2026-09-17", models: [
        { model: "demo-model", requests: 3, total_tokens: 150, cost_usd: 0.25 },
        { model: null, requests: 1, total_tokens: 50, cost_usd: 0 },
        { model: "premium-model", requests: 1, total_tokens: 10, cost_usd: 0.5 },
      ] },
      { date: "2026-09-18", models: [] },
    ],
  };
}

describe("Usage page", () => {
  beforeEach(() => {
    viewer.userId = "admin-id";
    viewer.isAdmin = true;
    viewer.canReadNames = true;
    vi.mocked(fetchAllDailyUsage).mockReset().mockImplementation((range) =>
      Promise.resolve(usage(range?.start ?? "2026-08-20")));
    vi.mocked(fetchUserDailyUsage).mockReset().mockImplementation((_id, range) =>
      Promise.resolve(usage(range?.start ?? "2026-08-20")));
    vi.mocked(fetchUsagePeople).mockReset().mockResolvedValue({
      timezone: "Europe/Berlin", start_date: "2026-09-01", end_date: "2026-09-18",
      users: [
        { user_id: "admin-id", requests: 3, total_tokens: 150, cost_usd: 0.25 },
        { user_id: "other-id", requests: 1, total_tokens: 50, cost_usd: 0.125 },
      ],
    });
    vi.mocked(fetchUser).mockReset().mockImplementation((id) => Promise.resolve({
      id, username: id, firstName: id === "other-id" ? "Other" : "Admin",
      lastName: "User", createdTimestamp: 0,
    }));
  });

  it("starts with all users for usage admins and ranks named people before switching scope", async () => {
    const user = userEvent.setup();
    render(<UsagePage />);
    expect(await screen.findByRole("region", { name: "Usage by model" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "User" })).toHaveValue("all");
    expect(within(screen.getByRole("region", { name: "Usage per person" }))
      .getByRole("combobox", { name: "Rank by" })).toHaveValue("cost_usd");
    expect(fetchAllDailyUsage).toHaveBeenCalledWith(undefined, expect.any(AbortSignal));
    expect(fetchAllDailyUsage).toHaveBeenCalledWith(
      { start: "2026-09-01", end: "2026-09-18" }, expect.any(AbortSignal));
    expect(fetchUsagePeople).toHaveBeenCalledWith(
      { start: "2026-09-01", end: "2026-09-18" }, expect.any(AbortSignal));
    await waitFor(() => { expect(screen.getByRole("button", { name: /Other User/ })).toBeInTheDocument(); });
    const people = within(screen.getByRole("region", { name: "Usage per person" })).getAllByRole("button");
    expect(people[0]).toHaveTextContent("Admin User");
    expect(people[1]).toHaveTextContent("Other User");
    expect(people[0]?.querySelector("[style]")).toHaveStyle({ width: "100%" });
    expect(people[1]?.querySelector("[style]")).toHaveStyle({ width: "50%" });
    await user.click(screen.getByRole("button", { name: /Other User/ }));
    await waitFor(() => {
      expect(fetchUserDailyUsage).toHaveBeenCalledWith(
        "other-id", { start: "2026-09-01", end: "2026-09-18" }, expect.any(AbortSignal));
    });
    expect(screen.queryByRole("region", { name: "Usage per person" })).not.toBeInTheDocument();
  });

  it("shows personal usage without offering an all-users request to a regular user", async () => {
    viewer.userId = "viewer-id";
    viewer.isAdmin = false;
    viewer.canReadNames = false;
    render(<UsagePage />);
    expect(await screen.findByRole("region", { name: "Usage by model" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "User" })).not.toBeInTheDocument();
    expect(screen.getByText("Tokens / request")).toBeInTheDocument();
    expect(fetchUserDailyUsage).toHaveBeenCalledWith(
      "viewer-id", { start: "2026-09-01", end: "2026-09-18" }, expect.any(AbortSignal));
    expect(fetchAllDailyUsage).not.toHaveBeenCalled();
    expect(fetchUsagePeople).not.toHaveBeenCalled();
  });

  it("ranks models by USD by default and updates their order and bars with the chosen metric", async () => {
    const user = userEvent.setup();
    viewer.isAdmin = false;
    render(<UsagePage />);
    const models = await screen.findByRole("region", { name: "Usage by model" });
    const selector = within(models).getByRole("combobox", { name: "Rank by" });
    const rows = () => within(models).getAllByRole("row").slice(1);
    expect(selector).toHaveValue("cost_usd");
    expect(rows()[0]).toHaveTextContent("premium-model");
    expect(rows()[0]?.querySelector("[style]")).toHaveStyle({ width: "100%" });
    expect(rows()[1]?.querySelector("[style]")).toHaveStyle({ width: "50%" });

    await user.selectOptions(selector, "total_tokens");
    expect(rows()[0]).toHaveTextContent("demo-model");
    await user.selectOptions(selector, "requests");
    expect(rows()[0]).toHaveTextContent("demo-model");
  });

  it("defaults the stacked trend to USD and offers tokens and requests in the same selector style", async () => {
    const user = userEvent.setup();
    render(<UsagePage />);
    const trend = await screen.findByRole("region", { name: "Usage trend" });
    expect(within(trend).getByRole("heading", { name: "Usage Trend" })).toBeInTheDocument();
    const selector = within(trend).getByRole("combobox", { name: "Show" });
    expect(selector).toHaveValue("cost_usd");
    expect(within(trend).getByLabelText("Daily USD by requested model")).toBeInTheDocument();
    expect(within(trend).queryByLabelText("Requested model legend")).not.toBeInTheDocument();

    await user.selectOptions(selector, "total_tokens");
    expect(within(trend).getByLabelText("Daily tokens by requested model")).toBeInTheDocument();
    await user.selectOptions(selector, "requests");
    expect(within(trend).getByLabelText("Daily requests by requested model")).toBeInTheDocument();
    expect(selector).toHaveValue("requests");
    expect(screen.queryByRole("region", { name: "Request trend" })).not.toBeInTheDocument();
  });

  it("keeps the dashboard usable for usage admins without Keycloak directory access", async () => {
    viewer.canReadNames = false;
    render(<UsagePage />);
    expect(await screen.findByRole("region", { name: "Usage per person" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Usage per person" }))
      .getByRole("button", { name: /other-id/ })).toBeInTheDocument();
    expect(fetchUser).not.toHaveBeenCalled();
  });
});
