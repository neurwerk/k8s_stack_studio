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
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="table w-full text-left text-sm">
        <thead><tr className="border-b border-border text-muted-foreground">
          <th className="px-4 py-3 font-medium">URL</th><th className="px-4 py-3 font-medium">Type</th>
        </tr></thead>
        <tbody>{view?.catalog.endpoints.map((endpoint) => {
          const destinations = view.catalog.destinations.filter((item) => item.endpoint_ids.includes(endpoint.id));
          const profiles = [...new Set(destinations.flatMap((item) => item.profile_ids))];
          const profileLabels: Record<string, string> = {
            "openai-codex-responses-v1": "OpenAI Codex",
            "openai-responses-v1": "OpenAI Responses",
          };
          return <tr key={endpoint.id} className="border-b border-border hover:bg-muted/50">
            <td className="break-all px-4 py-3 font-mono text-xs">{endpoint.url}</td>
            <td className="px-4 py-3">{endpoint.entry_mode === "api"
              ? destinations.some((item) => item.kind === "mcp") ? "MCP" : "API"
              : endpoint.url.startsWith("https:") ? "HTTPS forward proxy" : "HTTP forward proxy"}
              {endpoint.entry_mode === "forward_proxy" && profiles.length > 0 &&
                <p className="mt-1 text-xs text-muted-foreground">Configured routes: {profiles.map((id) => profileLabels[id] ?? id).join(", ")}</p>}
            </td>
          </tr>;
        })}
        {!view?.catalog.endpoints.length && <tr><td colSpan={2} className="px-4 py-3 text-muted-foreground">
          {loading ? "Loading endpoints…" : view ? "No endpoints available." : "Gateway information unavailable."}
        </td></tr>}</tbody>
      </table>
    </div>
  </main>;
}
