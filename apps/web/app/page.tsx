"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useCurrentUserId } from "@/lib/auth/roles";

export default function Home() {
  const router = useRouter();
  const userId = useCurrentUserId();

  useEffect(() => {
    if (userId) router.replace(`/users/${encodeURIComponent(userId)}`);
  }, [router, userId]);

  return (
    <div className="flex h-full items-center justify-center" role="status" aria-live="polite">
      <div className="flex items-center gap-3 text-muted-foreground"><span className="loading loading-spinner loading-sm" />Loading...</div>
    </div>
  );
}
