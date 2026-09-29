import { apiGet, apiPut } from "@/lib/api/client";

export interface NoticePreferences {
  show_no_pii: boolean;
  show_pass: boolean;
  show_changes: boolean;
  show_reroutes: boolean;
  show_timing: boolean;
}

export type NoticeOverrides = { [K in keyof NoticePreferences]: boolean | null };

const path = "/me/notice-preferences";

export const getNoticePreferences = () => apiGet<NoticePreferences>(path);
export const saveNoticePreferences = (value: NoticePreferences) =>
  apiPut<NoticePreferences, NoticePreferences>(path, value);
export const getNoticeOverrides = (keyId: string) =>
  apiGet<NoticeOverrides>(`${path}/keys/${encodeURIComponent(keyId)}`);
export const saveNoticeOverrides = (keyId: string, value: NoticeOverrides) =>
  apiPut<NoticeOverrides, NoticeOverrides>(`${path}/keys/${encodeURIComponent(keyId)}`, value);
