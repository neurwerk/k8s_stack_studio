// The web dev container keeps .next in a named volume. Turbopack can retain a
// failed plugin resolution there even after pnpm installs the missing package.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const nextDir = join("apps", "web", ".next");
const cacheDir = join(nextDir, "cache");
const stamp = join(cacheDir, ".studio-dependencies");
const hash = createHash("sha256");
hash.update("studio-web-cache-v1");
hash.update(process.versions.node);
for (const file of ["pnpm-lock.yaml", join("apps", "web", "package.json")]) {
  hash.update(readFileSync(file));
}
const fingerprint = hash.digest("hex");

if (!existsSync(stamp) || readFileSync(stamp, "utf8") !== fingerprint) {
  // .next itself is a Docker volume mount point and cannot be removed (EBUSY).
  if (existsSync(nextDir)) {
    for (const entry of readdirSync(nextDir)) {
      rmSync(join(nextDir, entry), { recursive: true, force: true });
    }
  }
  mkdirSync(cacheDir, { recursive: true });
  writeFileSync(stamp, fingerprint);
  console.log("Cleared web dev cache after dependency change.");
}
