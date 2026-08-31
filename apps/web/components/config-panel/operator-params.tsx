import type { EntityPolicyEntry } from "@/lib/config-generator";

import { ParamInput } from "./param-input";

interface OperatorParamsProps {
  entry: EntityPolicyEntry;
  onChange: (e: EntityPolicyEntry) => void;
}

export function OperatorParams({ entry, onChange }: OperatorParamsProps) {
  if (["pass", "block", "reversible_replace", "redact", "reroute"].includes(entry.action)) return null;
  const setParam = (key: string, value: string) => {
    onChange({ ...entry, params: { ...entry.params, [key]: value } });
  };
  return (
    <div className="ml-1 mt-1 space-y-1.5 border-l-2 border-muted-foreground/20 pl-3">
      {entry.action === "mask" && (
        <>
          <ParamInput label="masking_char" value={entry.params.masking_char || "*"} maxLen={1} onChange={(v) => { setParam("masking_char", v); }} />
          <ParamInput label="chars_to_mask" value={entry.params.chars_to_mask || "100"} onChange={(v) => { setParam("chars_to_mask", v); }} />
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground w-[80px] shrink-0">from_end</span>
            <select
              value={entry.params.from_end || "true"}
              onChange={(e) => { setParam("from_end", e.target.value); }}
              className="text-[10px] border border-border rounded px-1.5 py-0.5 bg-background flex-1"
            >
              <option value="true">true</option><option value="false">false</option>
            </select>
          </div>
        </>
      )}
      {entry.action === "replace" && <ParamInput label="new_value" value={entry.params.new_value || "<ENTITY>"} onChange={(v) => { setParam("new_value", v); }} />}
      {entry.action === "hash" && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground w-[80px] shrink-0">hash_type</span>
            <select
              value={entry.params.hash_type || "sha256"}
              onChange={(e) => { setParam("hash_type", e.target.value); }}
              className="text-[10px] border border-border rounded px-1.5 py-0.5 bg-background flex-1"
            >
              <option value="sha256">sha256</option>
            </select>
          </div>
          <p className="text-[9px] text-muted-foreground/60 -mt-0.5">
            Salt is derived automatically per rolling window (default 24 h).
          </p>
        </>
      )}
      {entry.action === "encrypt" && <p className="text-[9px] text-muted-foreground/60">Uses the engine runtime encryption key; key material is never accepted from Studio.</p>}
    </div>
  );
}
