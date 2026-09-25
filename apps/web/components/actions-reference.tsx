/** PII Actions reference — collapsible table from the shared PII Engine registry. */

"use client";

import { useEffect, useState } from "react";
import { BookOpen, ChevronDown } from "lucide-react";
import type { ActionDef } from "@/lib/api/policy-engine";
import { getActions } from "@/lib/api/policy-engine";
import { FALLBACK_ACTIONS } from "@/lib/actions-fallback";

const SEVERITY_STYLES: Record<ActionDef["severity"], string> = {
  pass: "badge-success badge-outline",
  fail: "badge-error badge-outline",
  info: "badge-info badge-outline",
  warn: "badge-warning badge-outline",
};

function Badge({ label, severity }: { label: string; severity: ActionDef["severity"] }) {
  return (
    <span className={`badge badge-sm font-medium ${SEVERITY_STYLES[severity]}`}>
      {label}
    </span>
  );
}

export function ActionsReference() {
  const [actions, setActions] = useState<ActionDef[] | null>(null);
  const [show, setShow] = useState(false);
  const [fromLive, setFromLive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getActions()
      .then((res) => {
        if (cancelled || res.length === 0) return;
        setActions(res);
        setFromLive(true);
      })
      .catch(() => {
        if (!cancelled) setActions(FALLBACK_ACTIONS);
      });
    return () => { cancelled = true; };
  }, []);

  const items = actions ?? FALLBACK_ACTIONS;

  return (
    <div className="card overflow-hidden border border-border bg-card">
      <button
        onClick={() => { setShow(!show); }}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-foreground hover:bg-muted transition-colors"
      >
        <span className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-muted-foreground" />
          PII Actions Reference
          <span className="text-[9px] text-muted-foreground/60 font-normal">
            {fromLive ? "live from PII Engine" : "offline copy"}
          </span>
        </span>
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${
            show ? "rotate-180" : ""
          }`}
        />
      </button>
      <div
        className={`transition-all duration-300 ease-in-out overflow-y-auto ${
          show ? "max-h-[700px] opacity-100" : "max-h-0 opacity-0"
        }`}
      >
        <div className="px-4 pb-4 border-t border-border">
          <div className="pt-3 space-y-3">
            {items.map((a) => (
              <div key={a.name} className="rounded border border-border bg-background p-2.5 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[11px] font-mono font-semibold">{a.name}</span>
                  <Badge label={`decision: ${a.decision}`} severity={a.severity} />
                  <Badge label={`strictness: ${String(a.strictness)}`} severity={a.severity} />
                  <Badge label={a.reversible ? "reversible" : "not reversible"} severity={a.reversible ? "pass" : "info"} />
                  {a.params.length === 0 && (
                    <span className="text-[9px] text-muted-foreground/60">no operator params</span>
                  )}
                </div>
                {a.params.length > 0 && (
                  <div className="text-[9px] font-mono text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5">
                    {a.params.map((p) => (
                      <span key={p.name}>
                        {p.name}: {p.default || "(required)"}
                        {p.description ? ` — ${p.description}` : ""}
                      </span>
                    ))}
                  </div>
                )}
                <div className="text-[9px]">
                  <span className="text-muted-foreground/60">in: </span>
                   <span className="font-mono">{a.exampleInput ?? "PII value"}</span>
                  <span className="text-muted-foreground/60 ml-2">out: </span>
                   <span className="font-mono">{a.exampleOutput ?? "policy result"}</span>
                </div>
                {a.notes && (
                  <p className="text-[9px] text-muted-foreground/70">{a.notes}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
