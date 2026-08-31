import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

/** @typedef {{ OIDC_AUTHORITY?: string, OIDC_CLIENT_ID?: string }} RuntimeEnvironment */

/**
 * Serialize public runtime configuration as JavaScript without interpolation.
 *
 * @param {RuntimeEnvironment} env
 * @returns {string}
 */
export function serializeRuntimeEnv(env = process.env) {
  const values = {
    OIDC_AUTHORITY: env.OIDC_AUTHORITY ?? "",
    OIDC_CLIENT_ID: env.OIDC_CLIENT_ID ?? "",
  };
  const json = JSON.stringify(values)
    .replaceAll("<", "\\u003c")
    .replaceAll("\u2028", "\\u2028")
    .replaceAll("\u2029", "\\u2029");
  return `window.__ENV__ = ${json};\n`;
}

/**
 * Write runtime configuration to the public asset path.
 *
 * @param {string} outputPath
 * @param {RuntimeEnvironment} env
 */
export function writeRuntimeEnv(outputPath, env = process.env) {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, serializeRuntimeEnv(env), {
    encoding: "utf8",
    mode: 0o600,
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const outputPath = process.argv[2];
  if (!outputPath) {
    throw new Error("Usage: node write-runtime-env.mjs <output-path>");
  }
  writeRuntimeEnv(outputPath);
}
