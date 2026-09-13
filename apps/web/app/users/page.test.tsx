import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchRecentSignins, fetchUsers } from "@/lib/api/admin";
import type { KeycloakUser, RecentSignins } from "@/lib/api/admin";
import UsersPage from "./page";

vi.mock("@/lib/api/admin", () => ({ fetchUsers: vi.fn(), fetchRecentSignins: vi.fn() }));
vi.mock("@/lib/auth/roles", () => ({ useIsKeycloakAdmin: () => true }));
const alice: KeycloakUser = {
  id: "a",
  username: "alice",
  email: "a@example.com",
  firstName: "Alice",
  lastName: "",
  enabled: true,
  emailVerified: false,
  createdTimestamp: 0,
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(fetchUsers).mockReset().mockResolvedValue([alice]);
  vi.mocked(fetchRecentSignins).mockReset().mockRejectedValue(new Error("unavailable"));
});
afterEach(() => {
  vi.useRealTimers();
});
async function advance(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

it("keeps the user table when event activity fails and explains limited history", async () => {
  render(<UsersPage />);
  await advance();
  expect(screen.getByRole("link", { name: "alice" })).toBeInTheDocument();
  expect(screen.getByText("Unavailable")).toBeInTheDocument();
  expect(screen.getByText(/No record does not mean/)).toBeInTheDocument();
});

it("paginates bounded lists and resets pagination after debounced search", async () => {
  vi.mocked(fetchUsers).mockResolvedValue(
    Array.from({ length: 25 }, (_, index) => ({
      ...alice,
      id: String(index),
      username: `user-${String(index)}`,
    })),
  );
  render(<UsersPage />);
  await advance();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await advance();
  expect(fetchUsers).toHaveBeenLastCalledWith(undefined, 25, expect.any(AbortSignal));
  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "al" } });
  await advance(200);
  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "alice" } });
  await advance(299);
  expect(fetchUsers).toHaveBeenCalledTimes(2);
  await advance(1);
  expect(fetchUsers).toHaveBeenLastCalledWith("alice", 0, expect.any(AbortSignal));
  expect(screen.getByText("Page 1")).toBeInTheDocument();
});

it("aborts stale user requests and ignores late responses", async () => {
  let resolveOld!: (users: KeycloakUser[]) => void;
  vi.mocked(fetchUsers).mockReturnValueOnce(
    new Promise((resolve) => {
      resolveOld = resolve;
    }),
  );
  render(<UsersPage />);
  await advance();
  const oldSignal = vi.mocked(fetchUsers).mock.calls[0]?.[2];
  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "alice" } });
  expect(oldSignal?.aborted).toBe(true);
  await advance(300);
  await act(async () => {
    resolveOld([{ ...alice, username: "old-user" }]);
    await Promise.resolve();
  });
  expect(screen.queryByRole("link", { name: "old-user" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "alice" })).toBeInTheDocument();
});

it("does not apply old activity to a new search and aborts on unmount", async () => {
  let resolveOld!: (value: RecentSignins) => void;
  vi.mocked(fetchRecentSignins).mockReturnValueOnce(
    new Promise((resolve) => {
      resolveOld = resolve;
    }),
  );
  const { unmount } = render(<UsersPage />);
  await advance();
  const oldSignal = vi.mocked(fetchRecentSignins).mock.calls[0]?.[1];
  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "alice" } });
  await advance(300);
  await act(async () => {
    resolveOld({
      window_start: "2026-09-04T12:00:00Z",
      window_end: "2026-09-11T12:00:00Z",
      users: { a: { status: "no_record", timestamp: null } },
    });
    await Promise.resolve();
  });
  expect(oldSignal?.aborted).toBe(true);
  expect(screen.getByText("Unavailable")).toBeInTheDocument();
  expect(screen.queryByText("No record in last 7 days")).not.toBeInTheDocument();
  const currentSignal = vi.mocked(fetchRecentSignins).mock.calls[1]?.[1];
  unmount();
  expect(currentSignal?.aborted).toBe(true);
});
