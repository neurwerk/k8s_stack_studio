import type { DailyModelUsage, UsageDateRange, UserDailyUsage, UsagePerson, UsagePeriod, UsageMetric } from "@/lib/api/usage";

function emptyMetric(): UsageMetric {
  return { state: "known", reported_sum: 0, complete_total: 0, known_records: 0, total_records: 0 };
}

function emptyUsage() {
  return { requests: 0, total_tokens: 0, cost_usd: 0, accounting: { tokens: emptyMetric(), cost_usd: emptyMetric() } };
}

/** Roll up row evidence; older API responses never gain completeness from a numeric zero. */
function addUsage(target: ReturnType<typeof emptyUsage>, entry: UsagePeriod) {
  target.requests += entry.requests;
  target.total_tokens += entry.total_tokens;
  target.cost_usd += entry.cost_usd;
  for (const name of ["tokens", "cost_usd"] as const) {
    const metric = target.accounting[name];
    const source = entry.accounting?.[name];
    metric.reported_sum += source?.reported_sum ?? (name === "tokens" ? entry.total_tokens : entry.cost_usd);
    metric.total_records += entry.requests;
    metric.known_records += source?.known_records ?? 0;
    metric.state = metric.known_records === metric.total_records ? "known" : metric.known_records > 0 ? "partial" : "unknown";
    metric.complete_total = metric.state === "known" ? metric.reported_sum : null;
  }
}

export type UsagePreset = "month" | "7d" | "30d" | "last_month" | "custom";
export type PersonMetric = "total_tokens" | "cost_usd" | "requests";

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
  const totals = emptyUsage();
  const models = new Map<string | null, ReturnType<typeof emptyUsage> & { model: string | null }>();
  const daily = usage.days.map((day) => {
    const row = { date: day.date, ...emptyUsage() };
    for (const entry of day.models) {
      addUsage(row, entry);
      const model = models.get(entry.model) ?? {
        model: entry.model, ...emptyUsage(),
      };
      addUsage(model, entry);
      models.set(entry.model, model);
    }
    addUsage(totals, row);
    return row;
  });
  return {
    totals,
    models: [...models.values()].sort((a, b) => b.total_tokens - a.total_tokens ||
      (a.model ?? "").localeCompare(b.model ?? "")),
    daily,
  };
}

/** Give each displayed series a distinct color, regardless of the chart's ranking order. */
export function modelColors(models: readonly (string | null)[]): Map<string | null, string> {
  const colors = new Map<string | null, string>();
  if (models.includes(null)) colors.set(null, "#5f5f6b");
  const names = [...new Set(models.filter((model): model is string => model !== null))].sort();
  names.forEach((model, index) => {
    const hue = ((232 + index * 137.508) % 360).toFixed(1);
    colors.set(model, `hsl(${hue} 56% ${index % 2 === 0 ? "42" : "48"}%)`);
  });
  return colors;
}

/** One stack per requested model, preserving empty dates and unknown models. */
export function modelTrend(
  usage: UserDailyUsage, models: (string | null)[], metric: PersonMetric,
): ({ date: string } & Record<string, string | number>)[] {
  return usage.days.map((day) => ({
    date: day.date,
    ...Object.fromEntries(models.map((model, index) => [
      `model${String(index)}`,
      day.models.find((entry) => entry.model === model)?.[metric] ?? 0,
    ])),
  }));
}

/** Highest usage first; the opaque ID gives ties a stable order. */
export function rankPeople(people: UsagePerson[], metric: PersonMetric): UsagePerson[] {
  return [...people].sort((a, b) => b[metric] - a[metric] || a.user_id.localeCompare(b.user_id));
}

/** Rank requested models without changing the order used by the stacked trend. */
export function rankModels(models: DailyModelUsage[], metric: PersonMetric): DailyModelUsage[] {
  return [...models].sort((a, b) => b[metric] - a[metric] ||
    (a.model ?? "").localeCompare(b.model ?? ""));
}

/** Compare against the largest real value, including USD amounts below one dollar. */
export function usageBarWidth(value: number, largest: number): string {
  if (largest <= 0 || value <= 0) return "0%";
  return `${String(Math.max(2, value / largest * 100))}%`;
}
