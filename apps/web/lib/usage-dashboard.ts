import type { UsageDateRange, UserDailyUsage, UsagePerson } from "@/lib/api/usage";

export type UsagePreset = "month" | "7d" | "30d" | "last_month" | "custom";

const DAY_MS = 86_400_000;

function shiftDay(day: string, count: number): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) + count * DAY_MS).toISOString().slice(0, 10);
}

/** Work in API calendar labels, never in the browser's local timezone. */
export function presetRange(today: string, preset: Exclude<UsagePreset, "custom">): UsageDateRange {
  if (preset === "month") return { start: `${today.slice(0, 7)}-01`, end: today };
  if (preset === "7d") return { start: shiftDay(today, -6), end: today };
  if (preset === "30d") return { start: shiftDay(today, -29), end: today };
  const end = shiftDay(`${today.slice(0, 7)}-01`, -1);
  return { start: `${end.slice(0, 7)}-01`, end };
}

export function validRange(range: UsageDateRange, today: string): boolean {
  const days = (Date.parse(range.end) - Date.parse(range.start)) / DAY_MS + 1;
  return Boolean(range.start && range.end) && Number.isInteger(days) &&
    days >= 1 && days <= 90 && range.end <= today;
}

export function usageSummary(usage: UserDailyUsage) {
  const totals = { requests: 0, total_tokens: 0, cost_usd: 0 };
  const models = new Map<string | null, { model: string | null; requests: number; total_tokens: number; cost_usd: number }>();
  const daily = usage.days.map((day) => {
    const row = { date: day.date, requests: 0, total_tokens: 0, cost_usd: 0 };
    for (const entry of day.models) {
      row.requests += entry.requests;
      row.total_tokens += entry.total_tokens;
      row.cost_usd += entry.cost_usd;
      const model = models.get(entry.model) ?? {
        model: entry.model, requests: 0, total_tokens: 0, cost_usd: 0,
      };
      model.requests += entry.requests;
      model.total_tokens += entry.total_tokens;
      model.cost_usd += entry.cost_usd;
      models.set(entry.model, model);
    }
    totals.requests += row.requests;
    totals.total_tokens += row.total_tokens;
    totals.cost_usd += row.cost_usd;
    return row;
  });
  return {
    totals,
    models: [...models.values()].sort((a, b) => b.total_tokens - a.total_tokens ||
      (a.model ?? "").localeCompare(b.model ?? "")),
    daily,
  };
}

export type PersonMetric = "total_tokens" | "cost_usd" | "requests";

/** Highest usage first; the opaque ID gives ties a stable order. */
export function rankPeople(people: UsagePerson[], metric: PersonMetric): UsagePerson[] {
  return [...people].sort((a, b) => b[metric] - a[metric] || a.user_id.localeCompare(b.user_id));
}
