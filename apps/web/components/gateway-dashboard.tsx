"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { GatewayTrust } from "@/components/gateway-trust";
import { fetchGateway, fetchGatewayTrust } from "@/lib/api/gateway";
import type { GatewayProfile, GatewayView, HealthState, TrustManifest } from "@/lib/api/gateway";
import { useVerifiedSession } from "@/lib/auth/session-context";
import { credentialLabels, observationsCurrent, observedHealth } from "@/lib/gateway-view";

const panel = "card border border-border bg-card p-4 sm:p-6";
const healthLabels: Record<HealthState, string> = {
  available: "Available", unavailable: "Unavailable", unknown: "Health unknown",
};

function Health({ state }: { state: HealthState }) {
  return <span className={`badge badge-sm ${state === "available" ? "badge-success" : state === "unavailable" ? "badge-error" : "badge-outline"}`}>
    {healthLabels[state]}
  </span>;
}

export function GatewayDashboard({ administrator = false }: { administrator?: boolean }) {
  const session = useVerifiedSession();
  if (administrator && !session.realm_roles.includes("gateway-admin")) {
    return <main className="p-6"><h1 className="text-2xl font-semibold">Gateway administration</h1>
      <p className="mt-3 text-sm text-muted-foreground">The gateway-admin role is required to view configuration and health.</p>
    </main>;
  }
  return <GatewayContent administrator={administrator}
    key={JSON.stringify([administrator, session.subject, session.realm_roles, session.agentgateway_roles])} />;
}

interface Snapshot {
  request: number;
  view: GatewayView | null;
  trust: TrustManifest | null;
}

function GatewayContent({ administrator }: { administrator: boolean }) {
  const session = useVerifiedSession();
  const [refresh, setRefresh] = useState(0);
  const [snapshot, setSnapshot] = useState<Snapshot>({ request: -1, view: null, trust: null });
  const [now, setNow] = useState(() => Date.now());
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const loading = snapshot.request !== refresh;
  const { view } = snapshot;

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => { controller.abort(); }, 10_000);
    void Promise.allSettled([
      fetchGateway(administrator, controller.signal), fetchGatewayTrust(controller.signal),
    ]).then(([gateway, trust]) => {
      clearTimeout(timeout);
      if (active) setSnapshot({
        request: refresh,
        view: gateway.status === "fulfilled" ? gateway.value : null,
        trust: trust.status === "fulfilled" ? trust.value : null,
      });
    });
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [administrator, refresh]);

  useEffect(() => {
    const poll = setInterval(() => { setRefresh((value) => value + 1); }, 30_000);
    const clock = setInterval(() => { setNow(Date.now()); }, 1000);
    return () => { clearInterval(poll); clearInterval(clock); };
  }, []);

  const destinations = view?.catalog.destinations.filter((item) =>
    (kind === "all" || item.kind === kind) &&
    [item.display_name, item.id, item.provider_id, item.model].some((value) =>
      value?.toLowerCase().includes(query.toLowerCase().trim()))) ?? [];

  return <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold tracking-tight">{administrator ? "Gateway administration" : "AI Gateway"}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          {administrator ? "GitOps configuration and separately observed health. This view does not grant invocation access."
            : "Your permitted models, MCP integrations and applications. Access, operation support and live health are shown separately."}
        </p></div>
      <button type="button" disabled={loading} className="btn btn-outline btn-sm"
        onClick={() => { setRefresh((value) => value + 1); }}>
        <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden /> Refresh
      </button>
    </header>

    <nav aria-label="Gateway tools" className="flex flex-wrap gap-2">
      <Link className="btn btn-outline btn-sm" href="/api-keys">Neurwerk access keys</Link>
      {session.mcp_catalog_available && <Link className="btn btn-outline btn-sm" href="/mcp">MCP integrations</Link>}
      <Link className="btn btn-outline btn-sm" href="/usage">Usage</Link>
      {administrator ? <Link className="btn btn-outline btn-sm" href="/gateway">My gateway access</Link>
        : session.realm_roles.includes("gateway-admin") && <Link className="btn btn-outline btn-sm" href="/admin/gateway">Gateway administration</Link>}
      {administrator && session.realm_roles.includes("mcp-admin") && session.mcp_setup_available &&
        <Link className="btn btn-outline btn-sm" href="/admin/mcp">MCP Setup</Link>}
      {administrator && session.realm_roles.includes("pii-admin") &&
        <Link className="btn btn-outline btn-sm" href="/policy-engine">PII Policy</Link>}
    </nav>

    {!view ? <section className={panel} role="status">
      <p className="text-sm text-muted-foreground">{loading ? "Loading gateway information…"
        : "Gateway information unavailable. Refresh to retry the current publication."}</p>
    </section> : <>
      <section className={panel} aria-labelledby="gateway-endpoints-heading">
        <h2 id="gateway-endpoints-heading" className="text-lg font-semibold">Configured endpoints</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {observationsCurrent(view, now) ? "Current internal gateway readiness is shown where observed. Provider health is not established by these checks."
            : "Gateway readiness is unknown: observations are missing, expired or do not match this configuration."}
        </p>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {view.catalog.endpoints.map((endpoint) => <div key={endpoint.id} className="rounded-lg border border-border p-3">
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{endpoint.entry_mode === "api" ? "API / MCP" : endpoint.url.toLowerCase().startsWith("https:") ? "HTTPS forward proxy" : "HTTP forward proxy"}</span>
              <Health state={observedHealth(view, "endpoints", endpoint.id, now)} /></div>
            <p className="mt-2 break-all font-mono text-sm">{endpoint.url}</p>
            <p className="mt-2 text-xs text-muted-foreground">Caller authentication: {endpoint.caller_auth_modes.map((mode) =>
              ({ oidc_bearer: "Keycloak sign-in", neurwerk_bearer: "Neurwerk bearer", proxy_basic: "Proxy Basic" })[mode]).join(", ")}</p>
          </div>)}
        </div>
        {!view.catalog.endpoints.length && <p className="mt-3 text-sm text-muted-foreground">No endpoints in this view.</p>}
      </section>

      {administrator && <GatewayRevisions view={view} now={now} />}

      <section className={panel} aria-labelledby="gateway-destinations-heading">
        <h2 id="gateway-destinations-heading" className="text-lg font-semibold">{administrator ? "Configured destinations" : "Your destinations"}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {administrator ? "Credential modes below are configured choices, not this administrator’s grants."
            : "Only your allowed provider credential modes are listed. Neurwerk access keys keep their own permissions and expiry."}
          {" "}Personal credentials belong in the approved client flow. Studio does not collect provider refresh tokens.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs">Find a destination
            <input className="input input-bordered w-full bg-base-100 text-sm" value={query} maxLength={200}
              onChange={(event) => { setQuery(event.target.value); }} placeholder="Name, model or provider" />
          </label>
          <div className="flex flex-col gap-1 text-xs">
            <label htmlFor="gateway-kind">Kind</label>
            <select id="gateway-kind" className="select select-bordered bg-base-100 text-sm" value={kind} onChange={(event) => { setKind(event.target.value); }}>
              <option value="all">All destinations</option><option value="model">Models</option>
              <option value="mcp">MCP</option><option value="application">Applications</option>
            </select>
          </div>
        </div>
        <div className="mt-4 space-y-3">
          {destinations.map((item) => <article key={`${item.kind}:${item.id}`} className="rounded-lg border border-border p-4">
            <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{item.display_name}</h3>
              <span className="badge badge-outline badge-sm">{item.kind === "mcp" ? "MCP" : item.kind}</span></div>
            <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{item.id}{item.provider_id ? ` · ${item.provider_id}` : ""}{item.model ? ` · ${item.model}` : ""}</p>
            <div className="mt-3 flex flex-wrap gap-2">{item.credential_modes.map((mode) =>
              <span key={mode.source} className="badge badge-outline">{credentialLabels[mode.source]}</span>)}</div>
            {!item.credential_modes.length && <p className="mt-2 text-sm text-muted-foreground">No provider credential mode {administrator ? "configured" : "granted"}.</p>}
            <p className="mt-3 break-words text-xs text-muted-foreground">Endpoints: {item.endpoint_ids.join(", ")}</p>
            <p className="mt-1 break-words text-xs text-muted-foreground">Profiles: {item.profile_ids.length ? item.profile_ids.join(", ") : "No operation profile published"}</p>
            {administrator && <details className="mt-3 text-xs"><summary className="cursor-pointer font-medium">Permission requirements</summary>
              <p className="mt-2 break-all font-mono">Destination (all): {item.required_permissions.join(", ")}</p>
              {item.credential_modes.map((mode) => <p key={mode.source} className="mt-1 break-all">
                {credentialLabels[mode.source]} (additional): <span className="font-mono">{mode.required_permissions.join(", ") || "None"}</span>
              </p>)}
            </details>}
          </article>)}
        </div>
        {!destinations.length && <p className="mt-4 text-sm text-muted-foreground">
          {view.catalog.destinations.length ? "No matching destinations." : administrator ? "No destinations configured." : "No destinations are currently granted to you."}
        </p>}
      </section>

      <section className={panel} aria-labelledby="gateway-profiles-heading">
        <h2 id="gateway-profiles-heading" className="text-lg font-semibold">Operation support</h2>
        <p className="mt-1 text-sm text-muted-foreground">Support applies only to each listed operation. A working login does not prove that inference, uploads, history or exports work.</p>
        <div className="mt-4 space-y-4">{view.catalog.profiles.map((profile) =>
          <Profile key={profile.id} profile={profile} health={observedHealth(view, "profiles", profile.id, now)} />)}</div>
        {!view.catalog.profiles.length && <p className="mt-3 text-sm text-muted-foreground">No operation profiles in this view. Support is unknown.</p>}
      </section>
    </>}

    <GatewayTrust manifest={snapshot.trust} loading={loading} now={now} />
  </main>;
}

function GatewayRevisions({ view, now }: { view: GatewayView; now: number }) {
  return <section className={panel} aria-labelledby="gateway-revisions-heading">
    <h2 id="gateway-revisions-heading" className="text-lg font-semibold">Desired and observed revisions</h2>
    <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
      {Object.entries({ "Desired catalog": view.catalog.catalog_revision, "Observation catalog": view.status.catalog_revision,
        "Desired policy": view.catalog.policy_revision, "Observed loaded policy marker": view.status.applied_policy_revision,
        "Observed at": view.status.observed_at, "Valid until": view.status.valid_until }).map(([label, value]) =>
        <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-all font-mono text-xs">{value ?? "Unknown"}</dd></div>)}
    </dl>
    <div className="mt-4 overflow-x-auto"><table className="table table-sm">
      <thead><tr><th>Profile</th><th>Desired revision</th><th>Observed revision</th></tr></thead>
      <tbody>{view.catalog.profiles.map((item) => <tr key={item.id}><td>{item.id}</td><td>{item.revision}</td>
        <td>{view.status.profiles.find((observed) => observed.id === item.id)?.revision ?? "Unknown"}</td></tr>)}</tbody>
    </table></div>
    <h3 className="mt-4 font-semibold">Observed inspection signers</h3>
    <p className="mt-1 text-xs text-muted-foreground">One configured inspection listener and serving address are sampled per replica using a fresh TLS handshake. Other listeners and existing tunnels are not verified.</p>
    <div className="mt-3 overflow-x-auto"><table className="table table-sm">
      <thead><tr><th>Replica / UID</th><th>Sampled listener</th><th>Chain</th><th>Signer SHA-256</th><th>Signer expiry</th><th>Observed at</th></tr></thead>
      <tbody>{(view.status.signers ?? []).map((signer) => {
        const current = signer.state === "verified" && view.status.valid_until !== null &&
          Date.parse(signer.observed_at) <= now && now < Date.parse(view.status.valid_until) &&
          signer.not_after !== null && now < Date.parse(signer.not_after);
        return <tr key={signer.pod_uid}><td>{signer.pod_name}<p className="font-mono text-xs">{signer.pod_uid}</p></td>
          <td>{signer.listener}</td><td>{current ? "Verified" : "Unknown"}</td>
          <td className="max-w-xs break-all font-mono text-xs">{signer.fingerprint_sha256 ?? "Unknown"}</td>
          <td>{signer.not_after ?? "Unknown"}</td><td>{signer.observed_at}</td></tr>;
      })}</tbody>
    </table></div>
    {!view.status.signers?.length && <p className="mt-2 text-xs text-muted-foreground">No current replica signer observations published.</p>}
  </section>;
}

function Profile({ profile, health }: { profile: GatewayProfile; health: HealthState }) {
  return <article className="min-w-0 rounded-lg border border-border p-3">
    <div className="flex flex-wrap items-center gap-2"><h3 className="break-all font-medium">{profile.id}</h3><Health state={health} /></div>
    <p className="mt-1 break-all font-mono text-xs text-muted-foreground">Revision: {profile.revision}</p>
    {profile.limitations.map((limit, index) => <p key={index} className="mt-2 text-sm text-muted-foreground">{limit}</p>)}
    <div className="mt-3 overflow-x-auto"><table className="table table-sm">
      <thead><tr><th>Operation</th><th>Declared support</th><th>Restoration</th><th>Evidence / limits</th></tr></thead>
      <tbody>{profile.operations.map((operation) => <tr key={operation.id}>
        <td>{operation.id}</td><td><span className="badge badge-outline badge-sm">{operation.support}</span></td>
        <td>{operation.restoration_scope}</td><td className="min-w-48 max-w-lg whitespace-normal break-words">
          {operation.evidence_ref ?? "No evidence reference published"}
          {operation.verified_at && <p className="mt-1 text-xs text-muted-foreground">Verified {operation.verified_at}</p>}
          {operation.limitations.map((limit, index) => <p key={index} className="mt-1 text-xs text-muted-foreground">{limit}</p>)}
        </td>
      </tr>)}</tbody>
    </table></div>
    {!profile.operations.length && <p className="mt-2 text-sm text-muted-foreground">No operations qualified.</p>}
  </article>;
}
