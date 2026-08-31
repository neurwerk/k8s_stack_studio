"use client";

import { Activity, Coins, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchUserUsage } from "@/lib/api/usage";
import type { UsagePeriod, UserUsage } from "@/lib/api/usage";

interface UsageCard {
  label: string;
  usage: UsagePeriod;
}

const POLL_INTERVAL_MS = 30_000;

function formatTokens(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function formatCost(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 4,
  }).format(value);
}

function usageCards(usage: UserUsage): UsageCard[] {
  return [
    { label: "Total", usage: usage.total },
    { label: "This month", usage: usage.this_month },
    { label: "Last month", usage: usage.last_month },
    { label: "Last 30 days", usage: usage.last_30_days },
    { label: "This week", usage: usage.this_week },
    { label: "Last week", usage: usage.last_week },
    { label: "Last 7 days", usage: usage.last_7_days },
    { label: "Today", usage: usage.today },
    { label: "Last 24 hours", usage: usage.last_24_hours },
  ];
}

function UsageMetric({ label, usage }: UsageCard): React.ReactNode {
  return (
    <div className="rounded-lg border border-border bg-muted/10 p-4">
      <p className="text-sm font-medium">{label}</p>
      <div className="mt-3 flex items-center gap-2 text-lg font-semibold">
        <Activity className="h-4 w-4 shrink-0 text-muted-foreground" />
        {formatTokens(usage.total_tokens)}
        <span className="text-sm font-normal text-muted-foreground">tokens</span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
        <Coins className="h-4 w-4 shrink-0" />
        {formatCost(usage.cost_usd)}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {formatTokens(usage.input_tokens)} input · {formatTokens(usage.output_tokens)} output
      </p>
    </div>
  );
}

/** Display live Langfuse token and cost usage for a Studio user. */
export function UserUsage({ userId }: { userId: string }): React.ReactNode {
  const [usage, setUsage] = useState<UserUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const loadUsage = (): void => {
      fetchUserUsage(userId)
        .then((data) => {
          if (!cancelled) {
            setUsage(data);
            setError(null);
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            setError(error instanceof Error ? error.message : "Failed to load usage");
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    loadUsage();
    const interval = window.setInterval(loadUsage, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [userId]);

  return (
    <section className="mt-6 rounded-lg border border-border bg-card p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Usage</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Langfuse token and USD cost usage. Refreshes every 30 seconds.
          </p>
        </div>
        <RefreshCw className="h-4 w-4 shrink-0 text-muted-foreground" />
      </div>

      {loading && (
        <div className="mt-6 text-sm text-muted-foreground animate-pulse">Loading usage…</div>
      )}
      {error && !usage && (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}
      {usage && (
        <>
          {error && (
            <p className="mt-4 text-sm text-amber-700">
              Showing the last successful result. Refresh failed: {error}
            </p>
          )}
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {usageCards(usage).map((card) => (
              <UsageMetric key={card.label} {...card} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
