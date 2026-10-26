"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Rectangle, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { fetchUser } from "@/lib/api/admin";
import { AccountingValue } from "@/components/accounting-value";
import { GatewayClassificationFilters } from "@/components/gateway-filters";
import type { GatewayFilters } from "@/lib/api/gateway-metadata";
import { fetchAllDailyUsage, fetchUsagePeople, fetchUsageSources, fetchUserDailyUsage } from "@/lib/api/usage";
import type { UsageDateRange, UsagePeople, UsageSources, UsageSource, UsagePersonSources, UserDailyUsage } from "@/lib/api/usage";
import { useCurrentUserId, useHasRole, useIsKeycloakAdmin } from "@/lib/auth/roles";
import { modelColors, modelTrend, presetRange, rankModels, usageBarWidth, usageSummary, validRange } from "@/lib/usage-dashboard";
import type { PersonMetric, UsagePreset } from "@/lib/usage-dashboard";

const panel = "card min-w-0 border border-border bg-card p-4 sm:p-6";
const control = "select select-bordered min-w-0 bg-base-100 text-sm";

function count(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function dollars(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 4,
  }).format(value);
}

function dayLabel(value: string): string {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
    .format(new Date(`${value}T00:00:00Z`));
}

interface UsageResult {
  key: string;
  range: UsageDateRange;
  usage: UserDailyUsage;
  people: UsagePeople | null;
  sources: UsageSources;
}

const appLabels = new Map<string, string>([
  ["open-webui", "Open WebUI"], ["openwebui", "Open WebUI"], ["librechat", "LibreChat"],
  ["studio", "Studio"], ["agentgateway", "AgentGateway"],
  ["dify", "Dify"],
]);

function SourceTable({ title, rows, credential, onSelect }: {
  title: string; rows: UsageSource[]; credential?: boolean; onSelect?: (source: UsageSource) => void;
}) {
  return <section className={panel} aria-label={title}>
    <h2 className="text-xl font-semibold">{title}</h2>
    <p className="mt-2 text-xs text-muted-foreground">{credential
      ? "Current saved key names, with stable IDs below; never secrets. Unavailable keys may be revoked, removed or inaccessible."
      : "Verified OIDC client IDs, not caller headers. Missing app attribution is shown as no recorded app."} {onSelect && "Select a row to filter usage."}</p>
    <div className="mt-4 overflow-x-auto">
      <table className="table w-full min-w-[560px] text-left text-sm">
        <thead><tr><th className="py-3">{credential ? "Platform API key" : "Originating app"}</th>
          <th className="px-3 text-right">Tokens</th><th className="px-3 text-right">Cost (USD)</th>
          <th className="pl-3 text-right">Native LLM records</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={JSON.stringify([row.id, row.kind])} className="border-t border-border">
          <td className="max-w-sm break-all py-3 pr-3">{row.id === null
            ? (credential ? "No recorded platform key" : "No recorded app")
            : <button type="button" disabled={!onSelect} className="text-left text-primary underline disabled:text-foreground disabled:no-underline" onClick={() => { onSelect?.(row); }}>
              {credential ? row.name ?? (row.name_status === "not_looked_up" ? "Name not looked up" : "Unavailable key") : appLabels.get(row.id) ?? row.id}
              {credential && <span className="mt-1 block text-xs text-muted-foreground">{row.kind === "personal" ? "Personal key" : row.kind === "managed" ? "Managed key" : "Unknown key kind"} · {row.id}</span>}
              {!credential && appLabels.has(row.id) && <span className="ml-2 text-xs text-muted-foreground">({row.id})</span>}
            </button>}</td>
          <td className="px-3 text-right"><AccountingValue metric={row.accounting?.tokens} reported={row.total_tokens} /></td>
          <td className="px-3 text-right"><AccountingValue metric={row.accounting?.cost_usd} reported={row.cost_usd} currency /></td>
          <td className="pl-3 text-right">{count(row.requests)}</td>
        </tr>)}{rows.length === 0 && <tr><td colSpan={4} className="py-6 text-muted-foreground">No usage in this range.</td></tr>}</tbody>
      </table>
    </div>
  </section>;
}

export default function UsagePage() {
  const userId = useCurrentUserId();
  const isAdmin = useHasRole("langfuse-admin");
  const canReadNames = useIsKeycloakAdmin();
  if (!userId) return <p className="p-6 text-sm text-muted-foreground">Loading usage…</p>;
  return <UsageDashboard key={`${userId}:${String(isAdmin)}`} userId={userId} isAdmin={isAdmin} canReadNames={canReadNames} />;
}

function UsageDashboard({ userId, isAdmin, canReadNames }: {
  userId: string; isAdmin: boolean; canReadNames: boolean;
}) {
  const [selected, setSelected] = useState(isAdmin ? "all" : userId);
  const [range, setRange] = useState<UsageDateRange>();
  const [preset, setPreset] = useState<UsagePreset>("month");
  const [draftStart, setDraftStart] = useState("");
  const [draftEnd, setDraftEnd] = useState("");
  const [metric, setMetric] = useState<PersonMetric>("cost_usd");
  const [modelMetric, setModelMetric] = useState<PersonMetric>("cost_usd");
  const [trendMetric, setTrendMetric] = useState<PersonMetric>("cost_usd");
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<UsageResult>();
  const [names, setNames] = useState<Record<string, string>>({});
  const [identities, setIdentities] = useState<Record<string, "human" | "service">>({});
  const [directory, setDirectory] = useState<UsagePersonSources[]>([]);
  const [personLimit, setPersonLimit] = useState(20);
  const resolvedProfiles = useRef(new Set<string>());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dateError, setDateError] = useState<string | null>(null);
  const [filters, setFilters] = useState<GatewayFilters>({});
  const key = JSON.stringify([selected, range?.start, range?.end, filters, refresh]);
  const shown = result?.key === key ? result : undefined;
  const ranked = useMemo(() => [...(shown?.sources.people ?? [])].sort((a, b) =>
    b.total[metric] - a.total[metric] || (a.user_id ?? "").localeCompare(b.user_id ?? "")), [shown?.sources.people, metric]);
  const visiblePeople = useMemo(() => selected === "all" ? ranked.slice(0, personLimit) : ranked,
    [ranked, personLimit, selected]);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const getDaily = (bounds?: UsageDateRange) => selected === "all"
          ? fetchAllDailyUsage(bounds, controller.signal, filters)
          : fetchUserDailyUsage(selected, bounds, controller.signal, filters);
        let usage = await getDaily(range);
        const bounds = range ?? presetRange(usage.today, "month");
        if (usage.start_date !== bounds.start || usage.end_date !== bounds.end) {
          usage = await getDaily(bounds);
        }
        const [people, sources] = await Promise.all([
          isAdmin ? fetchUsagePeople(bounds, controller.signal, filters) : Promise.resolve(null),
          fetchUsageSources(selected === "all" ? null : selected, bounds, controller.signal, filters),
        ]);
        if (controller.signal.aborted) return;
        setResult({ key, range: bounds, usage, people, sources });
        if (selected === "all") setDirectory(sources.people);
        setDraftStart(bounds.start);
        setDraftEnd(bounds.end);
      } catch {
        if (!controller.signal.aborted) setError("Unable to load usage. Please try again.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => { controller.abort(); };
  }, [selected, range, isAdmin, key, filters]);

  useEffect(() => { resolvedProfiles.current.clear(); }, [refresh, canReadNames]);

  useEffect(() => {
    if (!canReadNames) return;
    const controller = new AbortController();
    const ids = [...new Set([
      ...visiblePeople.map((item) => item.user_id).filter((id): id is string => id !== null),
      ...(selected !== "all" ? [selected] : []),
    ])].filter((id) => !resolvedProfiles.current.has(id));
    const resolve = async () => {
      for (let index = 0; index < ids.length; index += 4) {
        const found: Record<string, string> = {};
        const kinds: Record<string, "human" | "service"> = {};
        const users = await Promise.allSettled(ids.slice(index, index + 4).map((id) =>
          fetchUser(id, controller.signal)));
        if (controller.signal.aborted) return;
        users.forEach((item) => {
          if (item.status === "fulfilled") {
            const user = item.value;
            found[user.id] = [user.firstName, user.lastName].filter(Boolean).join(" ") || user.username;
            kinds[user.id] = user.serviceAccountClientId ? "service" : "human";
            resolvedProfiles.current.add(user.id);
          }
        });
        setNames((previous) => ({ ...previous, ...found }));
        setIdentities((previous) => ({ ...previous, ...kinds }));
      }
    };
    void resolve();
    return () => { controller.abort(); };
  }, [canReadNames, visiblePeople, selected]);

  const today = shown?.usage.today ?? result?.usage.today;
  const people = shown?.people?.users ?? [];
  const summary = shown ? usageSummary(shown.usage) : null;
  const colors = modelColors(summary?.models.map((model) => model.model) ?? []);
  const trend = shown && summary
    ? modelTrend(shown.usage, summary.models.map((model) => model.model), trendMetric)
    : [];
  const topStackIndexes = trend.map((day) =>
    summary?.models.findLastIndex((_, index) => Number(day[`model${String(index)}`]) > 0) ?? -1);
  const rankedModels = rankModels(summary?.models ?? [], modelMetric);
  const maxModelMetric = rankedModels[0]?.[modelMetric] ?? 0;
  const label = (id: string) => (canReadNames ? names[id] : undefined) ?? (id === userId ? "You" : "Identity unavailable");
  const activeIds = new Set(people.map((person) => person.user_id));
  const category = (person: UsagePersonSources) => {
    if (person.user_id === null) return "Unknown ownership";
    if ((canReadNames && identities[person.user_id] === "service") || person.credentials.some((key) => key.kind === "managed")) return "System / service accounts";
    if (canReadNames && identities[person.user_id] === "human") return "People";
    return "Unresolved identities";
  };
  const selectSource = (person: UsagePersonSources, source: UsageSource, credential = false) => {
    if (source.id === null || person.user_id === null) return;
    setSelected(person.user_id);
    setFilters(credential ? { ...filters, credential_id: source.id, credential_kind: source.kind === "personal" || source.kind === "managed" ? source.kind : "" } : { ...filters, app_id: source.id });
  };

  return (
    <main className="mx-auto max-w-[1600px] space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
          <p className="mt-1 text-sm text-muted-foreground">Native LLM records, token usage and cost completeness.</p>
        </div>
        <button type="button" onClick={() => { setRefresh((value) => value + 1); }}
          className="btn btn-outline inline-flex items-center gap-2">
          <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
        </button>
      </div>

      <section className={panel} aria-label="Usage filters">
        {isAdmin && (
          <label className="mb-4 flex max-w-md flex-col gap-1 text-xs font-medium text-muted-foreground">
            Person or account
            <select className={control} value={selected} onChange={(event) => { setSelected(event.target.value); }}>
              <option value="all">All people</option>
              <option value={userId}>My usage</option>
              {selected !== "all" && selected !== userId && !activeIds.has(selected) && (
                <option value={selected}>{label(selected)}</option>
              )}
              {["People", "System / service accounts", "Unresolved identities"].map((group) => <optgroup key={group} label={group}>
                {(selected === "all" ? ranked : directory).filter((person) => person.user_id !== null && person.user_id !== userId && activeIds.has(person.user_id) && category(person) === group).map((person) => person.user_id !== null && <option key={person.user_id} value={person.user_id}>{label(person.user_id)} · {person.user_id}</option>)}
              </optgroup>)}
            </select>
          </label>
        )}
        <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
          event.preventDefault();
          const chosen = { start: draftStart, end: draftEnd };
          if (!today || !validRange(chosen, today)) {
            setDateError("Choose 1 to 90 days, in order, ending no later than today.");
            return;
          }
          setDateError(null);
          setRange(chosen);
          setPreset("custom");
        }}>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">From
            <input aria-label="From" type="date" className="input input-bordered bg-base-100" value={draftStart}
              max={today} onChange={(event) => { setDraftStart(event.target.value); setPreset("custom"); }} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">To
            <input aria-label="To" type="date" className="input input-bordered bg-base-100" value={draftEnd}
              max={today} onChange={(event) => { setDraftEnd(event.target.value); setPreset("custom"); }} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">Range
            <select className={control} value={preset} onChange={(event) => {
              const next = event.target.value as UsagePreset;
              setPreset(next);
              if (next !== "custom" && today) {
                const chosen = presetRange(today, next);
                setDraftStart(chosen.start);
                setDraftEnd(chosen.end);
                setRange(chosen);
                setDateError(null);
              }
            }}>
              <option value="month">This month</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="last_month">Last month</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <button type="submit" className="btn btn-primary">Apply</button>
          <span className="pb-2 text-xs text-muted-foreground">
            {shown ? shown.usage.timezone : "Up to 90 days"}
          </span>
          {dateError && <p role="alert" className="w-full text-sm text-destructive">{dateError}</p>}
        </form>
        <details className="mt-4">
          <summary className="cursor-pointer text-sm">App, platform key and gateway filters</summary>
          <div className="mt-3"><GatewayClassificationFilters value={filters} onChange={setFilters} /></div>
        </details>
        {Object.values(filters).some(Boolean) && <button type="button" className="btn btn-outline mt-3" onClick={() => { setFilters({}); }}>Clear usage filters</button>}
      </section>

      {!shown && (
        <div className={panel} role={error ? "alert" : "status"}>
          {error ?? "Loading usage…"}
        </div>
      )}
      {shown && summary && (
        <>
          {loading && <p role="status" className="text-sm text-muted-foreground">Refreshing usage…</p>}
          {error && <p role="alert" className="text-sm text-destructive">{error} Showing the last loaded range.</p>}
          <section aria-label="Usage totals" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {([
              ["Tokens", <AccountingValue key="tokens" metric={summary.totals.accounting.tokens} reported={summary.totals.total_tokens} />],
              ["Cost (USD)", <AccountingValue key="cost" metric={summary.totals.accounting.cost_usd} reported={summary.totals.cost_usd} currency />],
              ["Native LLM records", count(summary.totals.requests)],
              ["Models", count(summary.models.length)],
              [selected === "all" ? "Recorded principals" : "Token completeness",
                selected === "all" ? count(ranked.filter((person) => person.user_id !== null).length) : summary.totals.accounting.tokens.state],
            ] as const).map(([title, value]) => (
              <div key={title} className={panel}>
                <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
                <p className="mt-3 text-2xl font-semibold tabular-nums sm:text-3xl">{value}</p>
              </div>
            ))}
          </section>
          <section className={panel} aria-label="Usage per person">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">{selected === "all" ? "Usage per person" : `Usage for ${label(selected)}`}</h2>
              <label className="text-xs text-muted-foreground">Rank by{" "}<select className={control} value={metric} onChange={(event) => { setMetric(event.target.value as PersonMetric); }}>
                <option value="total_tokens">Reported tokens</option><option value="cost_usd">Reported USD</option><option value="requests">Native LLM records</option>
              </select></label>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">Each person or account has one total. Apps and platform keys are alternate breakdowns of that same total, not extra usage. System accounts and unknown ownership are separate from people.</p>
            {shown.sources.key_name_enrichment && (shown.sources.key_name_enrichment.limit_reached || shown.sources.key_name_enrichment.lookup_failed) && <p role="status" className="mt-2 text-sm text-muted-foreground">
              {shown.sources.key_name_enrichment.limit_reached && "The 5,000-key name lookup limit was reached. "}
              {shown.sources.key_name_enrichment.lookup_failed && "Some key name lookups could not be completed. "}
              Names were looked up for {count(shown.sources.key_name_enrichment.looked_up_keys)} of {count(shown.sources.key_name_enrichment.eligible_keys)} eligible keys; other names were not looked up. All recorded usage remains included; this does not change token or cost completeness.
            </p>}
            {["People", "System / service accounts", "Unresolved identities", "Unknown ownership"].map((group) => {
              const members = visiblePeople.filter((person) => category(person) === group);
              return members.length > 0 && <section key={group} className="mt-5" aria-label={group}>
                {selected === "all" && <h3 className="font-semibold">{group}</h3>}
                {members.map((person) => <details key={person.user_id ?? "unknown"} open={selected !== "all"} className="mt-3 rounded-lg border border-border p-3">
                  <summary className="cursor-pointer">
                    <span className="font-medium">{person.user_id === null ? "Unknown ownership" : label(person.user_id)}</span>
                    {person.user_id !== null && <span className="ml-2 break-all text-xs text-muted-foreground">{person.user_id}</span>}
                    <span className="mt-2 flex flex-wrap gap-4 text-sm">
                      <span>Tokens: <AccountingValue metric={person.total.accounting?.tokens} reported={person.total.total_tokens} /></span>
                      <span>USD: <AccountingValue metric={person.total.accounting?.cost_usd} reported={person.total.cost_usd} currency /></span>
                      <span>Native LLM records: {count(person.total.requests)}</span>
                    </span>
                  </summary>
                  {person.user_id === null && <p className="mt-3 text-sm text-muted-foreground">No recorded principal. This usage is not assigned to a person or a system account.</p>}
                  <div className="mt-4 space-y-3">
                    <SourceTable title="Originating apps" rows={person.apps} onSelect={person.user_id === null ? undefined : (source) => { selectSource(person, source); }} />
                    <SourceTable title="Platform API keys" rows={person.credentials} credential onSelect={person.user_id === null ? undefined : (source) => { selectSource(person, source, true); }} />
                  </div>
                </details>)}
              </section>;
            })}
            {visiblePeople.length < ranked.length && <button type="button" className="btn btn-outline mt-4" onClick={() => { setPersonLimit((limit) => limit + 20); }}>Show 20 more people or accounts ({count(visiblePeople.length)} of {count(ranked.length)} shown)</button>}
            {ranked.length === 0 && <p className="mt-4 text-sm text-muted-foreground">No usage in this range.</p>}
          </section>
          <section className={panel} aria-label="Usage by model">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">Models</h2>
              <label className="text-xs text-muted-foreground">Rank by{" "}
                <select className={control} value={modelMetric}
                  onChange={(event) => { setModelMetric(event.target.value as PersonMetric); }}>
                  <option value="total_tokens">Reported tokens</option><option value="cost_usd">Reported USD</option>
                  <option value="requests">Native LLM records</option>
                </select>
              </label>
            </div>
            <div className="mt-5 overflow-x-auto">
              <table className="table w-full min-w-[640px] text-left text-sm">
                <thead className="border-b border-border text-xs uppercase text-muted-foreground">
                  <tr><th className="py-3 pr-4">Model</th><th className="px-3 text-right">Tokens</th>
                    <th className="px-3 text-right">Cost (USD)</th><th className="pl-3 text-right">Native LLM records</th></tr>
                </thead>
                <tbody>
                  {rankedModels.map((model) => (
                    <tr key={model.model ?? "unknown"} className="border-b border-border/70 last:border-0">
                      <td className="max-w-xs py-3 pr-4 font-medium">
                        <span className="break-all">{model.model ?? "Unknown model"}</span>
                        <div className="mt-2 h-1.5 rounded-full bg-muted">
                          <div className="h-full rounded-full bg-primary"
                            style={{ width: usageBarWidth(model[modelMetric], maxModelMetric) }} />
                        </div>
                      </td>
                      <td className="px-3 text-right tabular-nums"><AccountingValue metric={model.accounting?.tokens} reported={model.total_tokens} /></td>
                      <td className="px-3 text-right tabular-nums"><AccountingValue metric={model.accounting?.cost_usd} reported={model.cost_usd} currency /></td>
                      <td className="pl-3 text-right tabular-nums">{count(model.requests)}</td>
                    </tr>
                  ))}
                  {summary.models.length === 0 && (
                    <tr><td colSpan={4} className="py-8 text-center text-muted-foreground">No usage in this range.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className={panel} aria-label="Usage trend">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">Reported usage trend</h2>
              <label className="text-xs text-muted-foreground">Show{" "}
                <select className={control} value={trendMetric}
                  onChange={(event) => { setTrendMetric(event.target.value as PersonMetric); }}>
                  <option value="total_tokens">Reported tokens</option><option value="cost_usd">Reported USD</option>
                  <option value="requests">Native LLM records</option>
                </select>
              </label>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">Bars show reported sums only. Missing usage can produce an empty bar; it does not mean zero actual usage or free service.</p>
            {summary.models.length === 0 ? (
              <p className="py-12 text-center text-sm text-muted-foreground">No usage in this range.</p>
            ) : (
              <div className="mt-4 h-64 w-full min-w-0 sm:h-72"
                aria-label={`Daily ${trendMetric === "cost_usd" ? "USD" : trendMetric === "requests" ? "requests" : "tokens"} by requested model`}>
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <BarChart data={trend} accessibilityLayer margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                     <CartesianGrid vertical={false} stroke="var(--border-color)" />
                    <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={32}
                      tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} axisLine={false} tickLine={false} />
                    <YAxis width={65} allowDecimals={trendMetric !== "requests"}
                      tickFormatter={(value: number) => new Intl.NumberFormat("en-US", {
                        notation: "compact", maximumFractionDigits: trendMetric === "cost_usd" ? 4 : trendMetric === "requests" ? 0 : 1,
                        ...(trendMetric === "cost_usd" ? { style: "currency", currency: "USD" } : {}),
                      }).format(value)} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                      axisLine={false} tickLine={false} />
                    <Tooltip
                      cursor={{ fill: "var(--muted)", opacity: 0.3 }}
                       contentStyle={{ background: "var(--card)", color: "var(--foreground)", borderColor: "var(--border-color)", borderRadius: 8 }}
                      labelFormatter={(value) => typeof value === "string" ? value : typeof value === "number" ? String(value) : ""}
                      formatter={(value, name) => [trendMetric === "cost_usd" ? dollars(Number(value)) : count(Number(value)), String(name)]}
                    />
                    {summary.models.map((model, index) => (
                      <Bar key={JSON.stringify(model.model)} name={model.model ?? "Unknown model"}
                        dataKey={`model${String(index)}`} stackId="usage" fill={colors.get(model.model)}
                        stroke="var(--card)" strokeWidth={1}
                        maxBarSize={36} isAnimationActive={false}
                        shape={(props) => (
                          <Rectangle {...props} radius={topStackIndexes[props.index] === index ? [4, 4, 0, 0] : 0} />
                        )} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>
          <section className={panel} aria-label="Daily usage">
            <h2 className="text-xl font-semibold">Daily usage</h2>
            <div className="mt-4 max-h-[32rem] overflow-auto">
               <table className="table w-full min-w-[560px] text-left text-sm">
                 <thead className="sticky top-0 border-b border-border bg-card text-xs uppercase text-muted-foreground">
                  <tr><th className="py-3">Date</th><th className="px-3 text-right">Tokens</th>
                    <th className="px-3 text-right">Cost (USD)</th><th className="pl-3 text-right">Native LLM records</th></tr>
                </thead>
                <tbody>{[...summary.daily].reverse().map((day) => (
                  <tr key={day.date} className="border-b border-border/70 last:border-0">
                    <td className="py-3">{dayLabel(day.date)}</td>
                    <td className="px-3 text-right tabular-nums"><AccountingValue metric={day.accounting.tokens} reported={day.total_tokens} /></td>
                    <td className="px-3 text-right tabular-nums"><AccountingValue metric={day.accounting.cost_usd} reported={day.cost_usd} currency /></td>
                    <td className="pl-3 text-right tabular-nums">{count(day.requests)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
