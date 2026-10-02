"use client";

import { ApiKeyManager } from "@/components/api-key-manager";
import { useCurrentUserId } from "@/lib/auth/roles";
import { useVerifiedSession } from "@/lib/auth/session-context";

export default function ApiKeysPage() {
  const userId = useCurrentUserId();
  const noticeAvailable = useVerifiedSession().notice_preferences_available;
  if (!userId) return <p className="p-6 text-sm text-muted-foreground">Loading API keys…</p>;
  return <main className="mx-auto max-w-7xl p-4 sm:p-6">
    <ApiKeyManager userId={userId} canManage isSelf noticeAvailable={noticeAvailable} asPage />
  </main>;
}
