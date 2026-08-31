import { afterEach, describe, expect, it } from "vitest";

import { getOidcConfig } from "../settings";

describe("getOidcConfig", () => {
  afterEach(() => {
    delete window.__ENV__;
  });

  it("uses a registered path for the post-logout redirect", () => {
    window.__ENV__ = {
      OIDC_AUTHORITY: "https://auth.example.com/realms/example",
      OIDC_CLIENT_ID: "studio",
    };

    const config = getOidcConfig();

    expect(config).toHaveProperty("post_logout_redirect_uri", `${window.location.origin}/`);
  });
});
