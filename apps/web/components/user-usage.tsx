"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fetchUserDailyUsage } from "@/lib/api/usage";
import type { UsageDateRange, UserDailyUsage } from "@/lib/api/usage";
import { modelColor } from "@/lib/usage-dashboard";

const POLL_INTERVAL_MS = 30_000;
const DAY_MS = 86_400_000;
const controlClass = "input input-bordered bg-base-100 text-sm";

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

// Dates are calendar labels from the API, not instants in the browser's timezone.
function formatDate(date: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T00:00:00Z`));
}

function DateRangeSelector({
  usage,
  onChange,
}: {
  usage: UserDailyUsage;
  onChange: (range: UsageDateRange) => void;
}): React.ReactNode {
  const [start, setStart] = useState(usage.start_date);
  const [end, setEnd] = useState(usage.end_date);
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="mt-4 flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        const days = (Date.parse(end) - Date.parse(start)) / DAY_MS + 1;
        if (
          !start ||
          !end ||
          !Number.isFinite(days) ||
          days < 1 ||
          days > 90 ||
          end > usage.today
        ) {
          setError("Choose 1 to 90 days, in order, with no future dates.");
          return;
        }
        setError(null);
        onChange({ start, end });
      }}
    >
      <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
        Start date
        <input
          className={`${controlClass} min-w-0`}
          type="date"
          required
          max={usage.today}
          value={start}
          onChange={(event) => {
            setStart(event.target.value);
          }}
        />
      </label>
      <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">
        End date
        <input
          className={`${controlClass} min-w-0`}
          type="date"
          required
          max={usage.today}
          value={end}
          onChange={(event) => {
            setEnd(event.target.value);
          }}
        />
      </label>
      <button className="btn btn-primary" type="submit">
        Apply range
      </button>
      <span className="py-2 text-xs text-muted-foreground">90 days maximum, inclusive</span>
      {error && (
        <p role="alert" className="w-full text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}

/** Reset all per-user state synchronously when the target principal changes. */
export function UserUsage({ userId }: { userId: string }): React.ReactNode {
  return <UsagePanel key={userId} userId={userId} />;
}

function UsagePanel({ userId }: { userId: string }): React.ReactNode {
  const [range, setRange] = useState<UsageDateRange>();
  const [metric, setMetric] = useState<"total_tokens" | "cost_usd">("total_tokens");
  const [hidden, setHidden] = useState<Set<string | null>>(new Set());
  const [result, setResult] = useState<{ key: string; data: UserDailyUsage; updatedAt: number }>();
  const [failure, setFailure] = useState<{ key: string; message: string }>();
  const [now, setNow] = useState(0);
  const start = range?.start;
  const end = range?.end;
  const key = JSON.stringify([start, end]);
  const usage = result?.key === key ? result.data : undefined;
  const error = failure?.key === key ? failure.message : undefined;

  useEffect(() => {
    let cancelled = false;
    let pending = false;
    const load = async (): Promise<void> => {
      if (pending) return;
      pending = true;
      try {
        const data = await fetchUserDailyUsage(userId, start && end ? { start, end } : undefined);
        if (!cancelled) {
          setResult({ key, data, updatedAt: Date.now() });
          setFailure(undefined);
        }
      } catch (error: unknown) {
        if (!cancelled)
          setFailure({
            key,
            message: error instanceof Error ? error.message : "Failed to load usage",
          });
      } finally {
        pending = false;
      }
    };
    void load();
    const interval = window.setInterval(() => {
      setNow(Date.now());
      void load();
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [userId, start, end, key]);

  const models = [
    ...new Set(usage?.days.flatMap((day) => day.models.map((item) => item.model)) ?? []),
  ].sort((a, b) => (a ?? "").localeCompare(b ?? ""));
  const totals = { total_tokens: 0, cost_usd: 0, requests: 0 };
  for (const day of usage?.days ?? []) {
    for (const item of day.models) {
      totals.total_tokens += item.total_tokens;
      totals.cost_usd += item.cost_usd;
      totals.requests += item.requests;
    }
  }
  const chartData = usage?.days.map((day) => ({
    date: day.date,
    // Synthetic keys avoid treating requested model names containing dots as object paths.
    ...Object.fromEntries(
      models.map((model, index) => [
        `model${String(index)}`,
        day.models.find((item) => item.model === model)?.[metric] ?? 0,
      ]),
    ),
  }));
  const stale = usage && (error ?? (result && now - result.updatedAt >= POLL_INTERVAL_MS * 2));

  return (
    <section
      className="card mt-6 min-w-0 border border-border bg-card p-4 sm:p-6"
      aria-label="Usage"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Usage</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Daily usage by requested model. Refreshes every 30 seconds.
          </p>
        </div>
        <RefreshCw aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Chart metric"
          className="join border border-border"
        >
          {(["total_tokens", "cost_usd"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={metric === value}
              className={`btn btn-sm join-item ${metric === value ? "btn-primary" : "btn-ghost"}`}
              onClick={() => {
                setMetric(value);
              }}
            >
              {value === "total_tokens" ? "Tokens" : "USD"}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          onClick={() => {
            setRange(undefined);
          }}
        >
          Last 30 days (including today)
        </button>
      </div>
      {!usage && (
        <p role={error ? "alert" : "status"} className="mt-6 text-sm text-muted-foreground">
          {error ?? "Loading usage..."}{" "}
          {range ? `${range.start} to ${range.end}` : "Last 30 days including today."}
        </p>
      )}
      {usage && (
        <>
          <DateRangeSelector
            key={`${usage.start_date}/${usage.end_date}`}
            usage={usage}
            onChange={setRange}
          />
          <p className="mt-3 text-xs text-muted-foreground">
            {usage.start_date} to {usage.end_date} (inclusive). Timezone: {usage.timezone}.
          </p>
          {stale && (
            <p role="alert" className="alert alert-warning mt-3 text-sm">
              Stale data: showing the last successful result for this range.{" "}
              {error ? `Refresh failed: ${error}` : "Refresh is delayed."}
            </p>
          )}
          <dl className="my-5 grid grid-cols-3 gap-3 border-y border-border py-4">
            {[
              ["Tokens", formatTokens(totals.total_tokens)],
              ["Reported USD", formatCost(totals.cost_usd)],
              ["Calls", formatTokens(totals.requests)],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="mt-1 break-words text-base font-semibold tabular-nums sm:text-xl">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          {totals.requests === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No usage in this range.
            </p>
          ) : (
            <>
              <p className="mb-2 text-xs text-muted-foreground">
                {metric === "total_tokens" ? "Tokens" : "USD"} per day
              </p>
              <div
                className="h-64 w-full min-w-0 sm:h-72"
                aria-label={`Daily ${metric === "total_tokens" ? "tokens" : "USD"} by requested model`}
              >
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <BarChart
                    data={chartData}
                    accessibilityLayer
                    margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                  >
                    <CartesianGrid vertical={false} stroke="var(--border-color)" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={formatDate}
                      minTickGap={32}
                      tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      width={58}
                      tickFormatter={(value: number) =>
                        new Intl.NumberFormat("en-US", {
                          notation: "compact",
                          maximumFractionDigits: 2,
                          ...(metric === "cost_usd" ? { style: "currency", currency: "USD" } : {}),
                        }).format(value)
                      }
                      tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "var(--muted)", opacity: 0.3 }}
                      content={({ active, label }) => {
                         const day = usage.days.find((day) => day.date === label);
                         if (!active || !day) return null;
                         const dailyTotal = day.models.reduce(
                           (sum, item) => ({
                             tokens: sum.tokens + item.total_tokens,
                             cost: sum.cost + item.cost_usd,
                           }),
                           { tokens: 0, cost: 0 },
                         );
                        return (
                          <div className="max-h-64 max-w-[min(20rem,80vw)] overflow-auto rounded-md border border-border bg-card p-3 text-xs shadow-md">
                            <p className="mb-2 font-medium">
                              {day.date} ({usage.timezone})
                               {day.date === usage.today ? " - incomplete today" : ""}
                             </p>
                             <p className="border-b border-border pb-2 font-medium">
                               Total (all models): {formatTokens(dailyTotal.tokens)} tokens /{" "}
                               {formatCost(dailyTotal.cost)}
                             </p>
                            {day.models
                              .filter((item) => !hidden.has(item.model))
                              .map((item) => (
                                <div key={JSON.stringify(item.model)} className="mt-2">
                                  <p
                                    className="break-all font-medium"
                                    style={{ color: modelColor(item.model) }}
                                  >
                                    {item.model ?? "Unknown model"}
                                  </p>
                                  <p>
                                    {formatTokens(item.total_tokens)} tokens /{" "}
                                    {formatCost(item.cost_usd)} / {formatTokens(item.requests)}{" "}
                                    calls
                                  </p>
                                </div>
                              ))}
                          </div>
                        );
                      }}
                    />
                    {models.map((model, index) => (
                      <Bar
                        key={JSON.stringify(model)}
                        name={model ?? "Unknown model"}
                        dataKey={`model${String(index)}`}
                        stackId="usage"
                        fill={modelColor(model)}
                        hide={hidden.has(model)}
                        isAnimationActive={false}
                        maxBarSize={36}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div
                role="group"
                aria-label="Requested model legend"
                className="mt-3 flex max-h-40 flex-wrap gap-2 overflow-auto"
              >
                {models.map((model) => (
                  <button
                    key={JSON.stringify(model)}
                    type="button"
                    aria-pressed={!hidden.has(model)}
                     className={`btn btn-outline btn-sm h-auto min-w-0 max-w-full gap-2 py-1 text-xs ${hidden.has(model) ? "text-muted-foreground line-through" : ""}`}
                    onClick={() => {
                      setHidden((previous) => {
                        const next = new Set(previous);
                        if (next.has(model)) next.delete(model);
                        else next.add(model);
                        return next;
                      });
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{ backgroundColor: modelColor(model) }}
                    />
                    <span className="break-all">{model ?? "Unknown model"}</span>
                  </button>
                ))}
              </div>
              {models.every((model) => hidden.has(model)) && (
                <p className="mt-2 text-sm text-muted-foreground">
                  All models hidden. Select a legend item to show it.
                </p>
              )}
            </>
          )}
          <p className="mt-4 text-xs text-muted-foreground">
            Totals include all models, even hidden ones. Today ({usage.today}) is incomplete.
            Reported cost may omit unpriced requests.
          </p>
        </>
      )}
    </section>
  );
}
