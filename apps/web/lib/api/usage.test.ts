import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiGet } from "./client";
import { fetchUserDailyUsage, fetchUserUsage } from "./usage";

vi.mock("./client", () => ({ apiGet: vi.fn() }));

describe("usage API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset().mockResolvedValue({});
  });

  it("uses server calendar defaults and safely encodes opaque user IDs", async () => {
    await fetchUserDailyUsage("user/with space");
    expect(apiGet).toHaveBeenCalledWith("/users/user%2Fwith%20space/usage/daily", undefined);
  });

  it("sends both inclusive dates without timezone conversion", async () => {
    await fetchUserDailyUsage("user-a", { start: "2026-08-11", end: "2026-09-09" });
    expect(apiGet).toHaveBeenCalledWith("/users/user-a/usage/daily", {
      start: "2026-08-11",
      end: "2026-09-09",
    });
  });

  it("preserves the shipped totals client", async () => {
    await fetchUserUsage("user-a");
    expect(apiGet).toHaveBeenCalledWith("/users/user-a/usage");
  });
});
