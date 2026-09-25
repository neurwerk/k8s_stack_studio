"use client";

import { useAuth } from "react-oidc-context";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

function getReturnTo(state: unknown): string {
  if (!state || typeof state !== "object" || Array.isArray(state) || !("returnTo" in state)) {
    return "/";
  }
  const { returnTo } = state;
  if (
    typeof returnTo !== "string" ||
    !returnTo.startsWith("/") ||
    returnTo.startsWith("//") ||
    /[\\\s]|\p{Cc}/u.test(returnTo)
  ) {
    return "/";
  }

  try {
    const url = new URL(returnTo, window.location.origin);
    // Check decoded and normalized paths too, without rewriting the saved deep link.
    const path = decodeURIComponent(url.pathname);
    if (path.startsWith("//") || /\\|\p{Cc}/u.test(path)) {
      return "/";
    }
    const normalized = new URL(path, window.location.origin);
    const pathname = normalized.pathname.replace(/\/{2,}/g, "/");
    if (
      url.origin !== window.location.origin ||
      normalized.origin !== window.location.origin ||
      pathname === "/auth/callback" ||
      pathname.startsWith("/auth/callback/")
    ) {
      return "/";
    }
    return returnTo;
  } catch {
    return "/";
  }
}

/** OIDC callback page — react-oidc-context handles the redirect automatically. */
export default function AuthCallback() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!auth.isLoading && !auth.error && auth.isAuthenticated) {
      router.replace(getReturnTo(auth.user?.state));
    }
  }, [auth.isLoading, auth.error, auth.isAuthenticated, auth.user?.state, router]);

  if (auth.error) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="alert alert-error max-w-md" role="alert">Sign-in failed: {auth.error.message}</div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="flex items-center gap-3 text-muted-foreground"><span className="loading loading-spinner loading-sm" />Completing sign-in…</div>
    </div>
  );
}
