import type { UsageMetric } from "@/lib/api/usage";

export function AccountingValue({ metric, reported, currency = false }: {
  metric?: UsageMetric; reported: number; currency?: boolean;
}) {
  const format = (value: number) => new Intl.NumberFormat("en-US", currency
    ? { style: "currency", currency: "USD", maximumFractionDigits: 6 } : {}).format(value);
  const complete = metric?.state === "known" ? metric.complete_total : null;
  const value = complete ?? ((metric?.known_records ?? 0) > 0 || (metric?.reported_sum ?? reported) !== 0
    ? metric?.reported_sum ?? reported : null);
  return value === null ? null : <span>{format(value)}</span>;
}
