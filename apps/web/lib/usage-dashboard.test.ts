import { describe, expect, it } from "vitest";

import type { UserDailyUsage } from "@/lib/api/usage";
import { presetRange, rankPeople, usageSummary, validRange } from "@/lib/usage-dashboard";

describe("usage dashboard calendar and aggregation", () => {
  it("uses calendar labels through month and daylight-saving boundaries", () => {
    expect(presetRange("2026-03-01", "last_month")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(presetRange("2026-03-31", "7d")).toEqual({ start: "2026-03-25", end: "2026-03-31" });
    expect(presetRange("2026-11-02", "month")).toEqual({ start: "2026-11-01", end: "2026-11-02" });
    expect(validRange({ start: "2026-03-29", end: "2026-03-30" }, "2026-03-30")).toBe(true);
    expect(validRange({ start: "2026-03-31", end: "2026-03-30" }, "2026-03-30")).toBe(false);
    expect(validRange({ start: "2026-01-01", end: "2026-04-01" }, "2026-04-01")).toBe(false);
  });

  it("adds sparse per-model days without dropping unknown models or mutating ranking input", () => {
    const usage: UserDailyUsage = {
      timezone: "Europe/Berlin", start_date: "2026-03-29", end_date: "2026-03-31",
      today: "2026-03-31", days: [
        { date: "2026-03-29", models: [
          { model: "model-a", requests: 2, total_tokens: 100, cost_usd: 0.2 },
          { model: null, requests: 1, total_tokens: 50, cost_usd: 0 },
        ] },
        { date: "2026-03-30", models: [] },
        { date: "2026-03-31", models: [
          { model: "model-a", requests: 1, total_tokens: 25, cost_usd: 0.1 },
        ] },
      ],
    };
    const result = usageSummary(usage);
    expect(result.totals.requests).toBe(4);
    expect(result.totals.total_tokens).toBe(175);
    expect(result.totals.cost_usd).toBeCloseTo(0.3);
    expect(result.models.map((model) => model.model)).toEqual(["model-a", null]);
    expect(result.daily[1]).toEqual({ date: "2026-03-30", requests: 0, total_tokens: 0, cost_usd: 0 });
    const people = [
      { user_id: "user-b", requests: 3, total_tokens: 20, cost_usd: 2 },
      { user_id: "user-a", requests: 1, total_tokens: 100, cost_usd: 1 },
    ];
    expect(rankPeople(people, "total_tokens").map((person) => person.user_id)).toEqual(["user-a", "user-b"]);
    expect(rankPeople(people, "cost_usd").map((person) => person.user_id)).toEqual(["user-b", "user-a"]);
    expect(people.map((person) => person.user_id)).toEqual(["user-b", "user-a"]);
  });
});
