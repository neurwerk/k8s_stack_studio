"use client";

import { NoticeSettings } from "@/components/notice-preferences";
import { useVerifiedSession } from "@/lib/auth/session-context";

export default function NoticesPage() {
  const available = useVerifiedSession().notice_preferences_available;
  return <main className="mx-auto max-w-7xl p-4 sm:p-6">
    {available ? <NoticeSettings asPage /> : (
      <p className="p-6 text-sm text-muted-foreground">Notice settings are unavailable.</p>
    )}
  </main>;
}
