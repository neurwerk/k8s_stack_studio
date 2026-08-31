import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { EntityPolicyEntry } from "@/lib/config-generator";
import { VALID_ACTIONS } from "@/lib/config-generator";

import { ParamInput } from "./param-input";
import { OperatorParams } from "./operator-params";
import { PatternEditor } from "./pattern-editor";

interface EntityRowProps {
  entry: EntityPolicyEntry;
  onChange: (e: EntityPolicyEntry) => void;
  onRemove: () => void;
}

export function EntityRow({ entry, onChange, onRemove }: EntityRowProps) {
  const [showPatterns, setShowPatterns] = useState(entry.patterns.length > 0);
  return (
    <div className="rounded border border-border bg-background p-2 space-y-1.5">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={entry.entityType}
          onChange={(e) => { onChange({ ...entry, entityType: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_") }); }}
          className="text-[10px] font-mono font-medium border border-border rounded px-1.5 py-1 bg-muted/30 flex-1 uppercase"
          placeholder="ENTITY_TYPE"
        />
        <select
          value={entry.action}
          onChange={(e) => {
            onChange({
              ...entry,
              action: e.target.value,
              routeClass: e.target.value === "reroute" ? (entry.routeClass || "local") : undefined,
              params: e.target.value !== entry.action ? {} : entry.params,
            });
          }}
          className="text-[10px] border border-border rounded px-1.5 py-1 bg-background w-28"
        >
          {VALID_ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <button onClick={onRemove} className="text-muted-foreground hover:text-red-500 shrink-0" title="Remove"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      {entry.action === "reroute" && (
        <ParamInput label="routeClass" value={entry.routeClass || ""} onChange={(v) => { onChange({ ...entry, routeClass: v }); }} />
      )}
      <OperatorParams entry={entry} onChange={onChange} />
      <button
        onClick={() => { setShowPatterns(!showPatterns); }}
        className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
      >
        <Plus className="h-3 w-3" /> {showPatterns ? "Hide" : "Add"} regex patterns ({entry.patterns.length})
      </button>
      {showPatterns && <PatternEditor patterns={entry.patterns} onChange={(p) => { onChange({ ...entry, patterns: p }); }} />}
    </div>
  );
}
