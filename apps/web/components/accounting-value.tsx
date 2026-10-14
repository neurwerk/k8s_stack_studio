import type { UsageMetric } from "@/lib/api/usage";

export function AccountingValue({ metric, reported, currency = false }: {
  metric?: UsageMetric; reported: number; currency?: boolean;
}) {
  const format = (value: number) => new Intl.NumberFormat("en-US", currency
    ? { style: "currency", currency: "USD", maximumFractionDigits: 6 } : {}).format(value);
  const complete = metric?.state === "known" ? metric.complete_total : null;
  return <span className="inline-flex flex-col gap-1">
    <span>{complete !== null ? format(complete) : metric?.state === "partial" ? "Partial" : "Unknown"}</span>
    {complete !== null
      ? <span className="text-xs font-normal text-muted-foreground">Known for selected records</span>
      : (metric?.reported_sum ?? reported) !== 0 || (metric?.known_records ?? 0) > 0
        ? <span className="text-xs font-normal text-muted-foreground">Reported sum: {format(metric?.reported_sum ?? reported)}</span>
        : <span className="text-xs font-normal text-muted-foreground">No complete total</span>}
  </span>;
}
