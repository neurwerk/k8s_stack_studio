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

it("keeps category choices saved when the user turns extra notices off", async () => {
  const user = userEvent.setup();
  render(<NoticeSettings />);
  await screen.findByLabelText("Extra notices (master)");
  await user.selectOptions(screen.getByLabelText("Faces not scanned"), "off");
  await user.selectOptions(screen.getByLabelText("Extra notices (master)"), "off");
  expect(screen.getByLabelText("Faces not scanned")).toBeDisabled();
  expect(screen.getByText(/does not hide API errors or turn off scanning/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save notices" }));
  await waitFor(() => {
    expect(api.saveNoticePreferences).toHaveBeenCalledWith({
      ...enabled, notices_enabled: false, show_unscanned_faces: false,
    });
  });
  await user.selectOptions(screen.getByLabelText("Extra notices (master)"), "on");
  expect(screen.getByLabelText("Faces not scanned")).toHaveValue("off");
});

it("allows a key to turn notices on over an off user master while inheriting categories", async () => {
  const user = userEvent.setup();
  api.getNoticePreferences.mockResolvedValue({ ...enabled, notices_enabled: false });
  render(<NoticeSettings keyId="key-1" />);
  await screen.findByLabelText("Extra notices (master)");
  expect(screen.getByLabelText("Faces detected")).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Extra notices (master)"), "on");
  expect(screen.getByLabelText("Faces detected")).toBeEnabled();
  await user.selectOptions(screen.getByLabelText("Faces not scanned"), "off");
  await user.click(screen.getByRole("button", { name: "Save notices" }));
  await waitFor(() => {
    expect(api.saveNoticeOverrides).toHaveBeenCalledWith("key-1", {
      ...Object.fromEntries(Object.keys(enabled).map((key) => [key, null])),
      notices_enabled: true,
      show_unscanned_faces: false,
    });
  });
});
