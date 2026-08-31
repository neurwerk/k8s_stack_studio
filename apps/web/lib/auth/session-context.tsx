"use client";

import { createContext, useContext } from "react";
import type { VerifiedSession } from "@/lib/api/session";

const VerifiedSessionContext = createContext<VerifiedSession | null>(null);

interface VerifiedSessionProviderProps {
  children: React.ReactNode;
  session: VerifiedSession;
}

export function VerifiedSessionProvider({ children, session }: VerifiedSessionProviderProps) {
  return <VerifiedSessionContext value={session}>{children}</VerifiedSessionContext>;
}

export function useVerifiedSession(): VerifiedSession {
  const session = useContext(VerifiedSessionContext);
  if (!session) {
    throw new Error("useVerifiedSession must be used within VerifiedSessionProvider");
  }
  return session;
}
