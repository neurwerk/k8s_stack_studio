"use client";

import { useEffect, useState } from "react";
import { GatewayTrust } from "@/components/gateway-trust";
import { fetchGateway, fetchGatewayTrust } from "@/lib/api/gateway";
import type { GatewayView, TrustManifest } from "@/lib/api/gateway";
import { useVerifiedSession } from "@/lib/auth/session-context";

export function GatewayDashboard() {
  const session = useVerifiedSession();
  return <GatewayContent administrator={session.realm_roles.includes("gateway-admin")}
    trustPublicationAvailable={session.gateway_trust_available !== false}
    key={JSON.stringify([session.subject, session.realm_roles, session.agentgateway_roles])} />;
}

function GatewayContent({ administrator, trustPublicationAvailable }: {
  administrator: boolean;
  trustPublicationAvailable: boolean;
}) {
  const [view, setView] = useState<GatewayView | null>(null);
  const [trust, setTrust] = useState<TrustManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => { setNow(Date.now()); }, 30_000);
    return () => { clearInterval(timer); };
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      const timeout = setTimeout(() => { controller.abort(); }, 10_000);
      const [gateway, certificates] = await Promise.allSettled([
        fetchGateway(administrator, controller.signal),
        trustPublicationAvailable ? fetchGatewayTrust(controller.signal) : Promise.resolve(null),
      ]);
      clearTimeout(timeout);
      if (active) {
        setView(gateway.status === "fulfilled" ? gateway.value : null);
        setTrust(certificates.status === "fulfilled" ? certificates.value : null);
        setLoading(false);
      }
    };
    void load();
    return () => { active = false; controller.abort(); };
  }, [administrator, trustPublicationAvailable, now]);

  return <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
    <h1 className="text-2xl font-semibold tracking-tight">Gateway</h1>
    {trustPublicationAvailable ? <GatewayTrust manifest={trust} loading={loading} now={now} compact />
      : <p role="status" className="text-sm text-muted-foreground">Inspection certificate publication is disabled.</p>}
    {([
      ["self-hosted-api-providers", "Self-hosted API providers"],
      ["external-api-providers", "External API providers"],
      ["external-subscription-providers", "External subscription providers"],
      ["mcp-servers", "MCP servers"],
    ] as const).map(([group, label]) => <section key={group} className="space-y-3">
      <h2 className="text-lg font-semibold">{label}</h2>
      {view?.catalog[group].map((entry) => <article key={entry.id} className="space-y-3 rounded-lg border border-border bg-card p-4 text-sm">
        <h3 className="font-medium">{entry.display_name}</h3>
        {entry.provider_id && <p className="text-muted-foreground">Provider: {entry.provider_id}</p>}
        <ul className="space-y-2">{entry.routes.map((route) => <li key={route.id}>
          <div className="break-all font-mono text-xs">{route.url}</div>
          <div className="text-muted-foreground">{route.entry_mode === "api" ? "API" : "Forward proxy"} · Caller authentication: {route.caller_auth_modes.join(", ")}</div>
        </li>)}</ul>
        <ul className="space-y-2">{entry.destinations.map((destination) => <li key={`${destination.kind}:${destination.id}`}>
          <div>{destination.display_name} <span className="font-mono text-xs">{destination.id}</span></div>
          <div className="text-muted-foreground">Credential modes: {destination.credential_modes.map((mode) => ({company: "Company", caller_supplied: "Caller supplied", none: "None"})[mode.source]).join(", ") || "Not available"}</div>
          <div className="text-muted-foreground">Routes: {destination.endpoint_ids.join(", ")}</div>
          {!!destination.profile_ids.length && <div className="text-muted-foreground">Profiles: {destination.profile_ids.join(", ")}</div>}
        </li>)}</ul>
      </article>)}
      {!view?.catalog[group].length && <p role="status" className="text-sm text-muted-foreground">{loading ? "Loading…" : view ? "No entries available." : "Gateway information unavailable."}</p>}
    </section>)}
  </main>;
}
