import { runInNewContext } from "node:vm";

import { describe, expect, it } from "vitest";

import { serializeRuntimeEnv } from "../write-runtime-env.mjs";

describe("serializeRuntimeEnv", () => {
  it("preserves values without allowing JavaScript interpolation", () => {
    const authority = 'https://auth.example.com/realms/example";globalThis.pwned=true;//';
    const clientId = "studio\nclient</script>\u2028";

    const script = serializeRuntimeEnv({
      OIDC_AUTHORITY: authority,
      OIDC_CLIENT_ID: clientId,
    });
    const prefix = "window.__ENV__ = ";
    const encoded = script.slice(prefix.length, -2);
    const context: {
      window: { __ENV__?: { OIDC_AUTHORITY: string; OIDC_CLIENT_ID: string } };
      pwned?: boolean;
    } = { window: {} };

    runInNewContext(script, context);

    expect(script.startsWith(prefix)).toBe(true);
    expect(JSON.parse(encoded) as unknown).toEqual({
      OIDC_AUTHORITY: authority,
      OIDC_CLIENT_ID: clientId,
    });
    expect(context.window.__ENV__).toEqual({
      OIDC_AUTHORITY: authority,
      OIDC_CLIENT_ID: clientId,
    });
    expect(context.pwned).toBeUndefined();
    expect(script).not.toContain("</script>");
    expect(script).toContain("\\u003c");
    expect(script).toContain("\\u2028");
  });
});
