"use client";

import { AuthProvider } from "react-oidc-context";
import { getOidcConfig } from "@/lib/oidc/settings";

interface OidcProviderProps {
  children: React.ReactNode;
}

export function OidcProvider({ children }: OidcProviderProps) {
  return <AuthProvider {...getOidcConfig()}>{children}</AuthProvider>;
}