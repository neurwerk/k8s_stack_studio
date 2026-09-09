import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import type * as Recharts from "recharts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UserDailyUsage } from "@/lib/api/usage";
import { fetchUserDailyUsage } from "@/lib/api/usage";

import { UserUsage } from "../user-usage";

vi.mock("@/lib/api/usage", () => ({ fetchUserDailyUsage: vi.fn() }));
// jsdom has no layout; exercise the real chart with deterministic dimensions.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof Recharts>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <actual.ResponsiveContainer width={600} height={280}>
        {children}
      </actual.ResponsiveContainer>
    ),
  };
});

const usage: UserDailyUsage = {
  timezone: "America/Los_Angeles",
  start_date: "2026-08-11",
  end_date: "2026-09-09",
  today: "2026-09-09",
  days: [
    { date: "2026-09-08", models: [] },
    {
      date: "2026-09-09",
      models: [
        { model: "provider/model.v1", requests: 2, total_tokens: 1234, cost_usd: 0.125 },
        { model: null, requests: 1, total_tokens: 20, cost_usd: 0 },
      ],
    },
  ],
};

describe("UserUsage", () => {
  beforeEach(() => {
    vi.mocked(fetchUserDailyUsage).mockReset().mockResolvedValue(usage);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("uses server defaults, shows compact totals and switches metrics without refetching", async () => {
    const user = userEvent.setup();
    const { container } = render(<UserUsage userId="user-a" />);
    expect(await screen.findByText("1,254")).toBeInTheDocument();
    expect(fetchUserDailyUsage).toHaveBeenCalledWith("user-a", undefined);
    expect(screen.getByText("$0.125")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText(/Timezone: America\/Los_Angeles/)).toBeInTheDocument();
    expect(screen.getByText(/Reported cost may omit unpriced requests/)).toBeInTheDocument();
    expect(screen.getByLabelText("Start date")).toHaveValue("2026-08-11");
    expect(screen.getByLabelText("End date")).toHaveAttribute("max", "2026-09-09");
    await waitFor(() => {
      expect(container.querySelectorAll(".recharts-bar-rectangle").length).toBeGreaterThan(0);
    });
    const model = screen.getByRole("button", { name: "provider/model.v1" });
    const color = model.querySelector("span")?.style.backgroundColor;
    await user.click(screen.getByRole("button", { name: "USD" }));
    expect(screen.getByLabelText("Daily USD by requested model")).toBeInTheDocument();
    expect(model.querySelector("span")?.style.backgroundColor).toBe(color);
    await user.click(model);
    expect(model).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("1,254")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Unknown model" }));
    expect(screen.getByText(/All models hidden/)).toBeInTheDocument();
    expect(fetchUserDailyUsage).toHaveBeenCalledTimes(1);
  });

  it("shows both metrics in the keyboard-accessible daily tooltip", async () => {
    render(<UserUsage userId="user-a" />);
    await screen.findByText("1,254");
    const chart = await screen.findByRole("application");
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(await screen.findByText("1,234 tokens / $0.125 / 2 calls")).toBeInTheDocument();
    expect(
      screen.getByText(/2026-09-09 \(America\/Los_Angeles\) - incomplete today/),
    ).toBeInTheDocument();
  });

  it("validates inclusive ranges and removes prior-range data during loading and failures", async () => {
    render(<UserUsage userId="user-a" />);
    await screen.findByText("1,254");
    const form = screen.getByRole("button", { name: "Apply range" }).closest("form");
    if (!form) throw new Error("Missing date form");
    for (const [start, end] of [
      ["2026-06-11", "2026-09-09"],
      ["2026-09-09", "2026-09-08"],
      ["2026-09-09", "2026-09-10"],
    ]) {
      fireEvent.change(screen.getByLabelText("Start date"), { target: { value: start } });
      fireEvent.change(screen.getByLabelText("End date"), { target: { value: end } });
      fireEvent.submit(form);
      expect(screen.getByRole("alert")).toHaveTextContent("Choose 1 to 90 days");
    }
    expect(fetchUserDailyUsage).toHaveBeenCalledTimes(1);
    let reject: (error: Error) => void = () => {
      throw new Error("Request not started");
    };
    vi.mocked(fetchUserDailyUsage).mockImplementationOnce(
      () =>
        new Promise((_resolve, rejectPromise) => {
          reject = rejectPromise;
        }),
    );
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-06-12" } });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-09-09" } });
    fireEvent.submit(form);
    expect(screen.queryByText("1,254")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2026-06-12 to 2026-09-09");
    expect(fetchUserDailyUsage).toHaveBeenLastCalledWith("user-a", {
      start: "2026-06-12",
      end: "2026-09-09",
    });
    await act(async () => {
      reject(new Error("Unavailable"));
      await Promise.resolve();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Unavailable");
    expect(screen.queryByText("1,254")).not.toBeInTheDocument();
  });

  it("keeps model colors, metric and legend selection across a one-day range", async () => {
    const user = userEvent.setup();
    render(<UserUsage userId="user-a" />);
    await screen.findByText("1,254");
    const model = screen.getByRole("button", { name: "provider/model.v1" });
    const color = model.querySelector("span")?.style.backgroundColor;
    await user.click(model);
    await user.click(screen.getByRole("button", { name: "USD" }));
    vi.mocked(fetchUserDailyUsage).mockResolvedValue({
      ...usage,
      start_date: "2026-09-09",
      days: [
        {
          date: "2026-09-09",
          models: [{ model: "provider/model.v1", requests: 1, total_tokens: 7, cost_usd: 0.01 }],
        },
      ],
    });
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-09-09" } });
    await user.click(screen.getByRole("button", { name: "Apply range" }));
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(fetchUserDailyUsage).toHaveBeenLastCalledWith("user-a", {
      start: "2026-09-09",
      end: "2026-09-09",
    });
    expect(screen.getByLabelText("Daily USD by requested model")).toBeInTheDocument();
    const updatedModel = screen.getByRole("button", { name: "provider/model.v1" });
    expect(updatedModel).toHaveAttribute("aria-pressed", "false");
    expect(updatedModel.querySelector("span")?.style.backgroundColor).toBe(color);
    await user.click(screen.getByRole("button", { name: "Last 30 days (including today)" }));
    expect(fetchUserDailyUsage).toHaveBeenLastCalledWith("user-a", undefined);
  });

  it("never shows the previous user's data or accepts their late response", async () => {
    let resolve: (value: UserDailyUsage) => void = () => {
      throw new Error("Request not started");
    };
    vi.mocked(fetchUserDailyUsage).mockImplementationOnce(
      () =>
        new Promise((resolvePromise) => {
          resolve = resolvePromise;
        }),
    );
    const { rerender } = render(<UserUsage userId="user-a" />);
    vi.mocked(fetchUserDailyUsage).mockResolvedValue({ ...usage, days: [] });
    rerender(<UserUsage userId="user-b" />);
    expect(await screen.findByText("No usage in this range.")).toBeInTheDocument();
    await act(async () => {
      resolve(usage);
      await Promise.resolve();
    });
    expect(screen.queryByText("1,254")).not.toBeInTheDocument();
    vi.mocked(fetchUserDailyUsage).mockImplementationOnce(
      () =>
        new Promise(() => {
          /* Remain pending. */
        }),
    );
    rerender(<UserUsage userId="user-c" />);
    expect(screen.queryByText("No usage in this range.")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading usage");
  });

  it("polls every 30 seconds, marks failed or delayed refreshes stale, and cleans up", async () => {
    vi.useFakeTimers();
    const { unmount } = render(<UserUsage userId="user-a" />);
    await act(async () => {
      await Promise.resolve();
    });
    vi.mocked(fetchUserDailyUsage).mockRejectedValueOnce(new Error("Unavailable"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Stale data");
    expect(screen.getByText("1,254")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    vi.mocked(fetchUserDailyUsage).mockImplementation(
      () =>
        new Promise(() => {
          /* Remain pending. */
        }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Refresh is delayed");
    const calls = vi.mocked(fetchUserDailyUsage).mock.calls.length;
    unmount();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchUserDailyUsage).toHaveBeenCalledTimes(calls);
  });
});
