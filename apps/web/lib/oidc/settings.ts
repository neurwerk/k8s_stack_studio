/** OIDC client configuration for Keycloak.
 *
 *  Reads per-deployment values from window.__ENV__ (injected at container
 *  startup by docker-entrypoint.sh).  Falls back gracefully during SSR so
 *  that `next build` succeeds without deployment-specific env vars. */
import type { AuthProviderProps } from "react-oidc-context";

/** Runtime env injected by the entrypoint script at container boot. */
interface RuntimeEnv {
  OIDC_AUTHORITY?: string;
  OIDC_CLIENT_ID?: string;
}

declare global {
  interface Window {
    __ENV__?: RuntimeEnv;
  }
}

/** Build the OIDC config from runtime-injected environment. */
export function getOidcConfig(): AuthProviderProps {
  const authority = typeof window !== "undefined" ? window.__ENV__?.OIDC_AUTHORITY : undefined;
  const clientId = typeof window !== "undefined" ? window.__ENV__?.OIDC_CLIENT_ID : undefined;

  // Only throw on the client — missing values during SSR are expected
  // (Next.js tries to pre-render pages that may include the provider tree).
  if (typeof window !== "undefined" && (!authority || !clientId)) {
    throw new Error("Missing OIDC_AUTHORITY or OIDC_CLIENT_ID in window.__ENV__");
  }

  return {
    authority: authority ?? "",
    client_id: clientId ?? "",
    redirect_uri: typeof window !== "undefined" ? `${window.location.origin}/auth/callback` : "",
    post_logout_redirect_uri: typeof window !== "undefined" ? `${window.location.origin}/` : "",
    scope: "openid profile email",
    onSigninCallback: () => {
      window.history.replaceState({}, document.title, window.location.pathname);
    },
  };
}
