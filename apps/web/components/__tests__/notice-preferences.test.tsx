import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { NoticeSettings } from "../notice-preferences";

const api = vi.hoisted(() => ({
  getNoticePreferences: vi.fn(),
  getNoticeOverrides: vi.fn(),
  saveNoticePreferences: vi.fn(),
  saveNoticeOverrides: vi.fn(),
}));
vi.mock("@/lib/api/notice-preferences", () => api);

const enabled = {
  notices_enabled: true,
  show_no_pii: true,
  show_pass: true,
  show_changes: true,
  show_reroutes: true,
  show_timing: true,
  show_no_faces: true,
  show_detected_faces: true,
  show_unscanned_faces: true,
};

beforeEach(() => {
  vi.resetAllMocks();
  api.getNoticePreferences.mockResolvedValue(enabled);
  api.getNoticeOverrides.mockResolvedValue(Object.fromEntries(Object.keys(enabled).map((key) => [key, null])));
  api.saveNoticePreferences.mockResolvedValue(enabled);
  api.saveNoticeOverrides.mockResolvedValue(enabled);
});

it("switches every notice off and on with the master control", async () => {
  const user = userEvent.setup();
  render(<NoticeSettings />);
  await screen.findByLabelText("Extra notices (master)");
  await user.click(screen.getByLabelText("Faces not scanned"));
  await user.click(screen.getByLabelText("Extra notices (master)"));
  expect(screen.getByLabelText("Faces not scanned")).not.toBeChecked();
  expect(screen.getByLabelText("Faces not scanned")).toBeDisabled();
  expect(screen.getByText(/does not hide API errors or disable PII scanning/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save notices" }));
  await waitFor(() => {
    expect(api.saveNoticePreferences).toHaveBeenCalledWith({
      ...Object.fromEntries(Object.keys(enabled).map((key) => [key, false])),
    });
  });
  expect(screen.getByText(/take up to 5 minutes/)).toBeInTheDocument();
  await user.click(screen.getByLabelText("Extra notices (master)"));
  expect(screen.getByLabelText("Faces not scanned")).toBeChecked();
});

it("allows a key to turn notices on over an off user master while inheriting categories", async () => {
  const user = userEvent.setup();
  api.getNoticePreferences.mockResolvedValue({ ...enabled, notices_enabled: false });
  render(<NoticeSettings keyId="key-1" />);
  await screen.findByLabelText("Extra notices (master)");
  expect(screen.getByLabelText("Faces detected")).toBeDisabled();
  await user.click(screen.getByLabelText("Extra notices (master)"));
  expect(screen.getByLabelText("Faces detected")).toBeEnabled();
  await user.click(screen.getByLabelText("Faces not scanned"));
  await user.click(screen.getByRole("button", { name: "Save notices" }));
  await waitFor(() => {
    expect(api.saveNoticeOverrides).toHaveBeenCalledWith("key-1", {
      ...enabled,
      notices_enabled: true,
      show_unscanned_faces: false,
    });
  });
});
