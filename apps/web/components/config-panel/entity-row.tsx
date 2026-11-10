import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { EntityPolicyEntry } from "@/lib/config-generator";
import { isMcpSource, MCP_SOURCE_ACTIONS, MCP_SOURCE_PATTERN, VALID_ACTIONS } from "@/lib/config-generator";

import { ParamInput } from "./param-input";
import { OperatorParams } from "./operator-params";
import { PatternEditor } from "./pattern-editor";

interface EntityRowProps {
  entry: EntityPolicyEntry;
  onChange: (e: EntityPolicyEntry) => void;
  onRemove?: () => void;
  fixedName?: boolean;
  defaultTarget?: string;
  sourceRule?: boolean;
  usedNames?: string[];
}

export function EntityRow({ entry, onChange, onRemove, fixedName = false, defaultTarget = "local", sourceRule = false, usedNames = [] }: EntityRowProps) {
  const [showPatterns, setShowPatterns] = useState(entry.patterns.length > 0);
  const source = sourceRule || isMcpSource(entry.entityType);
  const invalidName = source && (!/^MCP_TOOL_[A-Z0-9_]+$/.test(entry.entityType) || usedNames.includes(entry.entityType));
  return (
    <div className="rounded border border-border bg-background p-2 space-y-1.5">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={entry.entityType}
          aria-label={source ? "MCP source classification" : "Entity type"}
          readOnly={fixedName}
          aria-invalid={invalidName}
          maxLength={64}
          pattern={source ? MCP_SOURCE_PATTERN : undefined}
          onChange={(e) => {
            const entityType = e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_");
            if (source && !entityType.startsWith("MCP_TOOL_")) return;
            const nextSource = source || isMcpSource(entityType);
            onChange({ ...entry, entityType,
              ...(nextSource ? { action: MCP_SOURCE_ACTIONS.includes(entry.action) ? entry.action : "block", params: {}, patterns: [] } : {}),
            });
          }}
          className="text-[10px] font-mono font-medium border border-border rounded px-1.5 py-1 bg-muted/30 flex-1 uppercase"
          placeholder="ENTITY_TYPE"
        />
        <select
          value={entry.action}
          onChange={(e) => {
            onChange({
              ...entry,
              action: e.target.value,
              routeClass: e.target.value === "reroute" ? (entry.routeClass || defaultTarget) : undefined,
              params: e.target.value !== entry.action ? {} : entry.params,
            });
          }}
          className="text-[10px] border border-border rounded px-1.5 py-1 bg-background w-28"
        >
          {(source ? MCP_SOURCE_ACTIONS : VALID_ACTIONS).map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        {!fixedName && <button onClick={onRemove} className="text-muted-foreground hover:text-red-500 shrink-0" title="Remove"><Trash2 className="h-3.5 w-3.5" /></button>}
      </div>
      {invalidName && <p className="text-[10px] text-error">Use a unique MCP_TOOL_ name with uppercase letters, digits or underscores (maximum 64 characters).</p>}
      {entry.action === "reroute" && (
        <><ParamInput label="routeClass" value={entry.routeClass || ""} onChange={(v) => { onChange({ ...entry, routeClass: v }); }} />{source && <p className="text-[10px] text-muted-foreground">Use an exact existing approved local destination ID. Empty uses the configured default target: {defaultTarget}.</p>}</>
      )}
      {!source && <OperatorParams entry={entry} onChange={onChange} />}
      {!source && <button
        onClick={() => { setShowPatterns(!showPatterns); }}
        className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
      >
        <Plus className="h-3 w-3" /> {showPatterns ? "Hide" : "Add"} regex patterns ({entry.patterns.length})
      </button>}
      {!source && showPatterns && <PatternEditor patterns={entry.patterns} onChange={(p) => { onChange({ ...entry, patterns: p }); }} />}
    </div>
  );
}
