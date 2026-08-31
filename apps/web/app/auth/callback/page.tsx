"use client";

import { useAuth } from "react-oidc-context";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** OIDC callback page — react-oidc-context handles the redirect automatically. */
export default function AuthCallback() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!auth.isLoading && auth.isAuthenticated) {
      router.replace("/");
    }
  }, [auth.isLoading, auth.isAuthenticated, router]);

  if (auth.error) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-destructive">
          Sign-in failed: {auth.error.message}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-muted-foreground animate-pulse">
        Completing sign-in…
      </div>
    </div>
  );
}