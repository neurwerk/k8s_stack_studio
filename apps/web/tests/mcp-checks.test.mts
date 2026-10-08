import assert from "node:assert/strict";
import { test } from "node:test";
import { McpChecks, checkSummary, afterDiscovery } from "../lib/mcp-checks.ts";
import { McpRefresh, waitForMcpRetry } from "../lib/mcp-refresh.ts";
import type { McpCatalogEntry, McpTool, McpCheckResult, McpConnectionStatus } from "../lib/api/mcp";

const entry = (id: string, extra: Partial<McpCatalogEntry> = {}): McpCatalogEntry => ({ id, name: `Fixture integration ${id}`, permitted: true,
  authentication_model: "no-authentication", connection_status: null, ...extra });
const tools: McpTool[] = [{ name: "fixture_tool", description: "Generic test tool", checks: {
  first: { name: "First check", tool: "fixture_tool", arguments: {}, display: null },
  second: { name: "Second check", tool: "fixture_tool", arguments: {}, display: null },
} }];
const passed: McpCheckResult = { status: "passed", checked_at: "2026-01-01T12:00:00Z", result: "{}",
  display_label: null, display_value: null };
const tick = () => new Promise<void>((resolve) => setImmediate(resolve));
async function settled(checks: McpChecks) {
  for (let i = 0; i < 100; i++) {
    await tick();
    if (Object.values(checks.states).every((state) => !state.busy)) return;
  }
  assert.fail("Queue did not settle");
}
class FixtureRateLimit extends Error { retryAfter = 30; }
type Driver = ConstructorParameters<typeof McpChecks>[0];
function driver(extra: Partial<Driver> = {}): Driver {
  return { tools: () => Promise.resolve(tools), check: () => Promise.resolve(passed),
    error: (error) => ({ message: "Fixture check unavailable", retryAfter: error instanceof FixtureRateLimit ? error.retryAfter : undefined }), ...extra };
}

void test("all permitted checks run once without expansion; disconnected, missing state and denied rows skip", async () => {
  const calls: string[] = [];
  const checks = new McpChecks(driver({ check: (id, check) => { calls.push(`${id}:${check}`); return Promise.resolve(passed); } }));
  checks.start(() => { /* No UI subscriber in this test. */ });
  const items = [entry("ready"), entry("personal", { authentication_model: "individual-authentication" }),
    entry("denied", { permitted: false }), entry("missing", { authentication_model: "individual-authentication" }),
    entry("unpublished", { publication: { state: "pending-discovery", checked_at: null, error_code: null } })];
  const disconnected: McpConnectionStatus = { status: "connect required", message: null, checked_at: null, retry_after: null };
  const connections = { personal: disconnected };
  checks.sync(items, connections, {});
  checks.sync(items.map((item) => ({ ...item })), { ...connections }, {});
  checks.recheck("denied");
  checks.recheck("personal");
  await settled(checks);
  assert.deepEqual(calls, ["ready:first", "ready:second"]);
  checks.sync(items, { personal: { ...disconnected, status: "connected" } }, {});
  await settled(checks);
  assert.deepEqual(calls, ["ready:first", "ready:second", "personal:first", "personal:second"]);
  checks.stop();
});

void test("twenty integrations use at most three concurrent requests and retain every result", async () => {
  let active = 0;
  let maximum = 0;
  const request = async <T,>(value: T) => { active++; maximum = Math.max(maximum, active); await tick(); active--; return value; };
  const checks = new McpChecks(driver({ tools: () => request(tools), check: () => request(passed) }));
  checks.start(() => { /* No UI subscriber in this test. */ });
  checks.sync(Array.from({ length: 20 }, (_, index) => entry(String(index))), {}, {});
  await settled(checks);
  assert.equal(maximum, 3);
  assert.equal(Object.values(checks.states).flatMap((state) => Object.keys(state.checks)).length, 40);
  checks.stop();
});

void test("a later passed check cannot hide an earlier tool failure or request failure", async () => {
  for (const transportFailure of [false, true]) {
    const checks = new McpChecks(driver({ check: (_id, id) => {
      if (id === "second") return Promise.resolve(passed);
      if (transportFailure) return Promise.reject(new Error("Fixture failure"));
      return Promise.resolve({ ...passed, status: "failed" });
    } }));
    checks.start(() => { /* No UI subscriber in this test. */ });
    checks.sync([entry("fixture")], {}, {});
    await settled(checks);
    assert.deepEqual(checkSummary(checks.states.fixture), transportFailure
      ? { label: "1 of 2 checks unavailable", failed: false }
      : { label: "1 of 2 checks failed", failed: true });
    checks.stop();
  }
});

void test("refresh coalesces, rejects stale results, and never overlaps runs for one integration", async () => {
  let release: () => void = () => assert.fail("Request not started");
  let toolCalls = 0;
  const calls: string[] = [];
  const checks = new McpChecks(driver({ tools: async () => {
    toolCalls++;
    if (toolCalls === 1) await new Promise<void>((resolve) => { release = resolve; });
    return tools;
  }, check: (id, check) => { calls.push(`${id}:${check}`); return Promise.resolve(passed); } }));
  checks.start(() => { /* No UI subscriber in this test. */ });
  const items = [entry("fixture")];
  checks.sync(items, {}, {});
  await tick();
  checks.sync(items, {}, {}, { fixture: true });
  assert.equal(checks.states.fixture?.message, "Refreshing integration…");
  checks.sync(items, {}, { fixture: 1 });
  checks.sync(items, {}, { fixture: 2 });
  checks.recheck("fixture");
  assert.equal(toolCalls, 1);
  release();
  await settled(checks);
  assert.equal(toolCalls, 2);
  assert.deepEqual(calls, ["fixture:first", "fixture:second"]);
  checks.sync(items, {}, { fixture: 2 });
  await tick();
  assert.equal(toolCalls, 2);
  checks.stop();
});

void test("setup replay starts once; unmount cancels queued checks and ignores in-flight completion", async () => {
  const releases: (() => void)[] = [];
  const signals: AbortSignal[] = [];
  let requests = 0;
  const checks = new McpChecks(driver({ tools: async (_id, value) => {
    requests++; signals.push(value);
    await new Promise<void>((resolve) => { releases.push(resolve); });
    return tools;
  } }));
  const items = Array.from({ length: 4 }, (_, index) => entry(String(index)));
  checks.start(() => { /* No UI subscriber in this test. */ });
  checks.sync(items, {}, {});
  checks.stop();
  checks.start(() => { /* No UI subscriber in this test. */ });
  checks.sync(items, {}, {});
  await tick();
  assert.equal(requests, 3);
  checks.stop();
  assert.equal(signals.every((signal) => signal.aborted), true);
  releases.forEach((release) => { release(); });
  await tick();
  assert.equal(requests, 3);
  assert.equal(Object.values(checks.states).every((state) => !Object.keys(state.checks).length), true);
});

void test("Retry-After pauses remaining requests and does not retry the failed check automatically", async (context) => {
  context.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1000 });
  const calls: string[] = [];
  const checks = new McpChecks(driver({ check: (_id, id) => {
    calls.push(id);
    if (calls.length === 1) return Promise.reject(new FixtureRateLimit());
    return Promise.resolve(passed);
  } }));
  checks.start(() => { /* No UI subscriber in this test. */ });
  checks.sync([entry("fixture")], {}, {});
  await tick();
  assert.deepEqual(calls, ["first"]);
  checks.recheck("fixture");
  context.mock.timers.tick(29_999);
  await tick();
  assert.deepEqual(calls, ["first"]);
  context.mock.timers.tick(1);
  await settled(checks);
  assert.deepEqual(calls, ["first", "second"]);
  assert.deepEqual(checkSummary(checks.states.fixture), { label: "1 of 2 checks unavailable", failed: false });
  checks.recheck("fixture");
  await settled(checks);
  assert.deepEqual(calls, ["first", "second", "first", "second"]);
  checks.stop();
});

void test("a Connect callback during an older refresh gets a fresh read, never stale checks", async () => {
  const items = [entry("fixture", { authentication_model: "individual-authentication" })];
  const unavailable: McpConnectionStatus = { status: "status unavailable", message: "Fixture status unavailable",
    checked_at: null, retry_after: null };
  let release: (value: McpConnectionStatus) => void = () => assert.fail("Read not started");
  let reads = 0;
  let calls = 0;
  const accepted: string[] = [];
  const checks = new McpChecks(driver({ check: () => { calls++; return Promise.resolve(passed); } }));
  checks.start(() => { /* No UI subscriber in this test. */ });
  checks.sync(items, { fixture: unavailable }, {});
  await settled(checks);
  assert.equal(calls, 0);
  const refresh = new McpRefresh<McpConnectionStatus>();
  const read = () => {
    reads++;
    return reads === 1 ? new Promise<McpConnectionStatus>((resolve) => { release = resolve; })
      : Promise.resolve({ ...unavailable, status: "connected" as const, message: null });
  };
  const accept = (connection: McpConnectionStatus) => {
    accepted.push(connection.status);
    checks.sync(items, { fixture: connection }, { fixture: 1 });
  };
  const first = refresh.request(read, accept);
  const callback = refresh.request(read, accept);
  assert.equal(callback, first);
  release({ ...unavailable, status: "connect required", message: null });
  await callback;
  await settled(checks);
  assert.equal(reads, 2);
  assert.deepEqual(accepted, ["connected"]);
  assert.equal(calls, 2);
  checks.stop();
});

void test("read-only saved-status retry waits for Retry-After and checks only a verified connection", async (context) => {
  context.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1000 });
  let reads = 0;
  let calls = 0;
  const items = [entry("fixture", { authentication_model: "individual-authentication" })];
  const unavailable: McpConnectionStatus = { status: "status unavailable", message: "Fixture status unavailable",
    checked_at: null, retry_after: 30 };
  const checks = new McpChecks(driver({ check: () => { calls++; return Promise.resolve(passed); } }));
  checks.start(() => { /* No UI subscriber in this test. */ });
  checks.sync(items, { fixture: unavailable }, {});
  const refresh = new McpRefresh<McpConnectionStatus>();
  const retry = refresh.request(async () => {
    await waitForMcpRetry(31_000);
    reads++;
    return { ...unavailable, status: "connected", message: null, retry_after: null };
  }, (connection) => { checks.sync(items, { fixture: connection }, { fixture: 1 }); });
  context.mock.timers.tick(29_999);
  await tick();
  assert.equal(reads, 0);
  assert.equal(calls, 0);
  context.mock.timers.tick(1);
  await retry;
  await settled(checks);
  assert.equal(reads, 1);
  assert.equal(calls, 2);
  checks.stop();
});

void test("discovery waits for a fresh publication before checks resume", async () => {
  let calls = 0;
  const checks = new McpChecks(driver({ tools: () => { calls++; return Promise.resolve(tools); } }));
  checks.start(() => { /* No UI subscriber in this test. */ });
  const marker = "2026-01-01T12:00:00Z";
  const published = (checked_at: string | null) => entry("fixture", {
    publication: { state: "published", checked_at, error_code: null },
  });
  for (const timestamp of [null, "2026-01-01T11:59:59Z", marker]) {
    checks.sync([afterDiscovery(published(timestamp), marker)], {}, { fixture: 1 });
    await tick();
    assert.equal(calls, 0);
  }
  checks.sync([afterDiscovery(published("2026-01-01T12:00:01Z"), marker)], {}, { fixture: 2 });
  await settled(checks);
  assert.equal(calls, 1);
  checks.stop();
});
