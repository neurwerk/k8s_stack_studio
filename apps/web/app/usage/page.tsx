"use client";

import { useEffect, useState } from "react";
import { BarChart3, RefreshCw } from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { fetchUser } from "@/lib/api/admin";
import { fetchAllDailyUsage, fetchUsagePeople, fetchUserDailyUsage } from "@/lib/api/usage";
import type { UsageDateRange, UsagePeople, UserDailyUsage } from "@/lib/api/usage";
import { useCurrentUserId, useHasRole, useIsKeycloakAdmin } from "@/lib/auth/roles";
import { presetRange, rankPeople, usageSummary, validRange } from "@/lib/usage-dashboard";
import type { PersonMetric, UsagePreset } from "@/lib/usage-dashboard";

const panel = "min-w-0 rounded-2xl border border-border bg-card p-4 shadow-sm dark:border-[#304159] dark:bg-[#1b2d43] sm:p-6";
const control = "h-10 min-w-0 rounded-lg border border-border bg-background px-3 text-sm text-foreground dark:border-[#405673] dark:bg-[#14243a]";

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
  const [metric, setMetric] = useState<PersonMetric>("total_tokens");
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<UsageResult>();
  const [names, setNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dateError, setDateError] = useState<string | null>(null);
  const key = JSON.stringify([selected, range?.start, range?.end, refresh]);
  const shown = result?.key === key ? result : undefined;

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const getDaily = (bounds?: UsageDateRange) => selected === "all"
          ? fetchAllDailyUsage(bounds, controller.signal)
          : fetchUserDailyUsage(selected, bounds, controller.signal);
        let usage = await getDaily(range);
        const bounds = range ?? presetRange(usage.today, "month");
        if (usage.start_date !== bounds.start || usage.end_date !== bounds.end) {
          usage = await getDaily(bounds);
        }
        const people = isAdmin ? await fetchUsagePeople(bounds, controller.signal) : null;
        if (controller.signal.aborted) return;
        setResult({ key, range: bounds, usage, people });
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
  }, [selected, range, isAdmin, key]);

  useEffect(() => {
    if (!canReadNames || !shown?.people) return;
    const controller = new AbortController();
    const ids = [...new Set([
      ...shown.people.users.slice(0, 20).map((item) => item.user_id),
      ...(selected !== "all" ? [selected] : []),
    ])];
    const resolve = async () => {
      const found: Record<string, string> = {};
      for (let index = 0; index < ids.length && !controller.signal.aborted; index += 4) {
        const users = await Promise.allSettled(ids.slice(index, index + 4).map((id) =>
          fetchUser(id, controller.signal)));
        users.forEach((item) => {
          if (item.status === "fulfilled") {
            const user = item.value;
            found[user.id] = [user.firstName, user.lastName].filter(Boolean).join(" ") || user.username;
          }
        });
      }
      if (!controller.signal.aborted) setNames((previous) => ({ ...previous, ...found }));
    };
    void resolve();
    return () => { controller.abort(); };
  }, [canReadNames, shown?.people, selected]);

  const today = shown?.usage.today ?? result?.usage.today;
  const people = shown?.people?.users ?? [];
  const summary = shown ? usageSummary(shown.usage) : null;
  const ranked = rankPeople(people, metric);
  const label = (id: string) => names[id] ?? (id === userId ? "You" : `${id.slice(0, 8)}…`);
  const activeIds = new Set(people.map((person) => person.user_id));

  return (
    <main className="mx-auto max-w-[1600px] space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
          <p className="mt-1 text-sm text-muted-foreground">AgentGateway requests, reported tokens and USD.</p>
        </div>
        <button type="button" onClick={() => { setRefresh((value) => value + 1); }}
          className={`${control} inline-flex items-center gap-2 hover:bg-muted`}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
        </button>
      </div>

      <section className={panel} aria-label="Usage filters">
        {isAdmin && (
          <label className="mb-4 flex max-w-md flex-col gap-1 text-xs font-medium text-muted-foreground">
            User
            <select className={control} value={selected} onChange={(event) => { setSelected(event.target.value); }}>
              <option value="all">All users</option>
              <option value={userId}>My usage</option>
              {selected !== "all" && selected !== userId && !activeIds.has(selected) && (
                <option value={selected}>{label(selected)}</option>
              )}
              {people.filter((person) => person.user_id !== userId).map((person) => (
                <option key={person.user_id} value={person.user_id}>
                  {label(person.user_id)}
                </option>
              ))}
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
            <input aria-label="From" type="date" className={control} value={draftStart}
              max={today} onChange={(event) => { setDraftStart(event.target.value); setPreset("custom"); }} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">To
            <input aria-label="To" type="date" className={control} value={draftEnd}
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
          <button type="submit" className={`${control} hover:bg-muted`}>Apply</button>
          <span className="pb-2 text-xs text-muted-foreground">
            {shown ? `${shown.usage.timezone} · Today is partial` : "Up to 90 days"}
          </span>
          {dateError && <p role="alert" className="w-full text-sm text-destructive">{dateError}</p>}
        </form>
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
              ["Tokens", count(summary.totals.total_tokens)],
              ["Reported USD", dollars(summary.totals.cost_usd)],
              ["Requests", count(summary.totals.requests)],
              ["Models", count(summary.models.length)],
              [selected === "all" ? "Active users" : "Tokens / request",
                selected === "all" ? count(people.length) : count(summary.totals.requests
                  ? Math.round(summary.totals.total_tokens / summary.totals.requests) : 0)],
            ] as const).map(([title, value]) => (
              <div key={title} className={panel}>
                <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
                <p className="mt-3 text-2xl font-semibold tabular-nums sm:text-3xl">{value}</p>
              </div>
            ))}
          </section>
          <p className={`${panel} text-sm text-muted-foreground`}>
            <strong className="text-foreground">What do these numbers mean?</strong>{" "}
            Requests are recorded gateway calls; tokens and USD are upstream-reported totals.
            USD may omit unpriced requests. Dates follow {shown.usage.timezone}.
          </p>

          <section className={panel} aria-label="Usage by model">
            <h2 className="text-xl font-semibold">Models</h2>
            <p className="mt-1 text-sm text-muted-foreground">Usage totals for the selected range.</p>
            <div className="mt-5 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="border-b border-border text-xs uppercase text-muted-foreground">
                  <tr><th className="py-3 pr-4">Model</th><th className="px-3 text-right">Tokens</th>
                    <th className="px-3 text-right">Reported USD</th><th className="pl-3 text-right">Requests</th></tr>
                </thead>
                <tbody>
                  {summary.models.map((model) => (
                    <tr key={model.model ?? "unknown"} className="border-b border-border/70 last:border-0">
                      <td className="max-w-xs py-3 pr-4 font-medium">
                        <span className="break-all">{model.model ?? "Unknown model"}</span>
                        <div className="mt-2 h-1.5 rounded-full bg-muted">
                          <div className="h-full rounded-full bg-[#a5f3d0]" style={{ width: `${String(Math.max(2,
                            model.total_tokens / Math.max(1, summary.models[0]?.total_tokens ?? 1) * 100))}%` }} />
                        </div>
                      </td>
                      <td className="px-3 text-right tabular-nums">{count(model.total_tokens)}</td>
                      <td className="px-3 text-right tabular-nums">{dollars(model.cost_usd)}</td>
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

          {isAdmin && selected === "all" && (
            <section className={panel} aria-label="Usage per person">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><h2 className="text-xl font-semibold">Usage per person</h2>
                  <p className="mt-1 text-sm text-muted-foreground">Top {count(Math.min(20, ranked.length))} of {count(ranked.length)} active users.</p></div>
                <label className="text-xs text-muted-foreground">Rank by{" "}
                  <select className={control} value={metric} onChange={(event) => { setMetric(event.target.value as PersonMetric); }}>
                    <option value="total_tokens">Tokens</option><option value="cost_usd">USD</option>
                    <option value="requests">Requests</option>
                  </select>
                </label>
              </div>
              <div className="mt-5 space-y-3">
                {ranked.slice(0, 20).map((person) => (
                  <button key={person.user_id} type="button" onClick={() => { setSelected(person.user_id); }}
                    className="grid w-full items-center gap-2 text-left text-sm hover:text-primary sm:grid-cols-[minmax(8rem,13rem)_minmax(0,1fr)_6rem]"
                    title={person.user_id}>
                    <span className="truncate">{label(person.user_id)}</span>
                    <span className="h-3 rounded-full bg-muted"><span className="block h-full rounded-full bg-[#a5f3d0]"
                      style={{ width: `${String(Math.max(2, person[metric] / Math.max(1, ranked[0]?.[metric] ?? 1) * 100))}%` }} /></span>
                    <span className="text-right tabular-nums">{metric === "cost_usd" ? dollars(person.cost_usd) : count(person[metric])}</span>
                  </button>
                ))}
                {ranked.length === 0 && <p className="text-sm text-muted-foreground">No attributed users in this range.</p>}
              </div>
              <p className="mt-4 text-xs text-muted-foreground">People are identified by verified gateway principals. Unattributed requests can appear in totals but not here.</p>
            </section>
          )}

          <div className="grid gap-5 xl:grid-cols-2">
            <section className={panel} aria-label="Token trend">
              <h2 className="mb-4 text-xl font-semibold">Token trend</h2>
              <div className="h-64 w-full min-w-0 sm:h-72">
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <AreaChart data={summary.daily} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} tick={{ fontSize: 11 }} />
                    <YAxis width={55} tickFormatter={(value: number) => new Intl.NumberFormat("en-US", { notation: "compact" }).format(value)} tick={{ fontSize: 11 }} />
                    <Tooltip labelFormatter={(value) => typeof value === "string" ? value : typeof value === "number" ? String(value) : ""} formatter={(value) => [count(Number(value)), "Tokens"]} />
                    <Area type="monotone" dataKey="total_tokens" stroke="#a5f3d0" fill="#a5f3d0" fillOpacity={0.2} isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </section>
            <section className={panel} aria-label="Request trend">
              <h2 className="mb-4 text-xl font-semibold">Request trend</h2>
              <div className="h-64 w-full min-w-0 sm:h-72">
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <BarChart data={summary.daily} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} tick={{ fontSize: 11 }} />
                    <YAxis width={42} allowDecimals={false} tick={{ fontSize: 11 }} />
                    <Tooltip labelFormatter={(value) => typeof value === "string" ? value : typeof value === "number" ? String(value) : ""} formatter={(value) => [count(Number(value)), "Requests"]} />
                    <Bar dataKey="requests" fill="#b7a4f7" radius={[4, 4, 0, 0]} maxBarSize={30} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>
          </div>

          <section className={panel} aria-label="Daily usage">
            <h2 className="text-xl font-semibold">Daily usage</h2>
            <div className="mt-4 max-h-[32rem] overflow-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead className="sticky top-0 border-b border-border bg-card text-xs uppercase text-muted-foreground dark:bg-[#1b2d43]">
                  <tr><th className="py-3">Date</th><th className="px-3 text-right">Tokens</th>
                    <th className="px-3 text-right">Reported USD</th><th className="pl-3 text-right">Requests</th></tr>
                </thead>
                <tbody>{[...summary.daily].reverse().map((day) => (
                  <tr key={day.date} className="border-b border-border/70 last:border-0">
                    <td className="py-3">{dayLabel(day.date)}{day.date === shown.usage.today ? " · Today (partial)" : ""}</td>
                    <td className="px-3 text-right tabular-nums">{count(day.total_tokens)}</td>
                    <td className="px-3 text-right tabular-nums">{dollars(day.cost_usd)}</td>
                    <td className="pl-3 text-right tabular-nums">{count(day.requests)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
        </>
      )}
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" /> Data is reported by AgentGateway; costs may omit unpriced requests.
      </p>
    </main>
  );
}
