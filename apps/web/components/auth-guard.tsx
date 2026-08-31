"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "react-oidc-context";
import { ApiRequestError } from "@/lib/api/client";
import { fetchSession } from "@/lib/api/session";
import type { VerifiedSession } from "@/lib/api/session";
import { VerifiedSessionProvider } from "@/lib/auth/session-context";

interface AuthGuardProps {
  children: React.ReactNode;
}

type SessionState =
  | { accessToken: string; status: "admitted"; session: VerifiedSession }
  | { accessToken: string; status: "denied" }
  | { accessToken: string; status: "error" };

/** Admits only verified OIDC users with the Studio application role. */
export function AuthGuard({ children }: AuthGuardProps) {
  const {
    activeNavigator,
    error,
    isAuthenticated,
    isLoading,
    removeUser,
    signinRedirect,
    signoutRedirect,
    user,
  } = useAuth();
  const redirectStarted = useRef(false);
  const [sessionState, setSessionState] = useState<SessionState | null>(null);
  const accessToken = user?.access_token;
  const currentSessionState = sessionState?.accessToken === accessToken ? sessionState : null;

  useEffect(() => {
    if (!isLoading && !error && !isAuthenticated && !activeNavigator && !redirectStarted.current) {
      redirectStarted.current = true;
      void signinRedirect();
    }
  }, [activeNavigator, error, isAuthenticated, isLoading, signinRedirect]);

  useEffect(() => {
    if (!isAuthenticated || !accessToken) return;

    let cancelled = false;
    void fetchSession()
      .then((session) => {
        if (!cancelled) setSessionState({ accessToken, status: "admitted", session });
      })
      .catch((sessionError: unknown) => {
        if (cancelled) return;
        if (sessionError instanceof ApiRequestError && sessionError.status === 401) {
          void removeUser();
          return;
        }
        if (sessionError instanceof ApiRequestError && sessionError.status === 403) {
          setSessionState({ accessToken, status: "denied" });
          return;
        }
        setSessionState({ accessToken, status: "error" });
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, isAuthenticated, removeUser]);

  if (isLoading || (isAuthenticated && !currentSessionState)) {
    return (
      <div className="flex h-full items-center justify-center" role="status" aria-live="polite">
        <div className="text-muted-foreground animate-pulse">Loading…</div>
      </div>
    );
  }

  if (error || currentSessionState?.status === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div
          className="max-w-md rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center text-sm"
          role="alert"
        >
          <p className="font-semibold text-destructive">Authentication unavailable</p>
          <p className="mt-1 text-muted-foreground">Please try signing in again.</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  if (currentSessionState?.status === "denied") {
    const isSigningOut = activeNavigator === "signoutRedirect";

    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div
          className="max-w-md rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center text-sm"
          role="alert"
        >
          <h1 className="font-semibold text-destructive">Access denied</h1>
          <p className="mt-1 text-muted-foreground">
            Your account is authenticated but is not allowed to use Studio. Contact an administrator
            to request the studio-user role.
          </p>
          <button
            type="button"
            onClick={() => {
              void signoutRedirect();
            }}
            disabled={isSigningOut}
            className="mt-4 rounded-md border border-border bg-background px-3 py-2 font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSigningOut ? "Logging out…" : "Log out and use another account"}
          </button>
        </div>
      </div>
    );
  }

  if (currentSessionState?.status !== "admitted") return null;

  return (
    <VerifiedSessionProvider session={currentSessionState.session}>{children}</VerifiedSessionProvider>
  );
}
