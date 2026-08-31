import { Trash2 } from "lucide-react";
import type { SafetyRule } from "@/lib/config-generator";

import { ParamInput } from "./param-input";

interface SafetyRuleRowProps {
  rule: SafetyRule;
  onChange: (r: SafetyRule) => void;
  onRemove: () => void;
}

export function SafetyRuleRow({ rule, onChange, onRemove }: SafetyRuleRowProps) {
  return (
    <div className="rounded border border-border bg-background p-2 space-y-1">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={rule.name}
          onChange={(e) => { onChange({ ...rule, name: e.target.value }); }}
          className="text-[11px] font-mono border border-border rounded px-2 py-1 bg-muted/30 flex-1"
          placeholder="rule-name"
        />
        <select
          value={rule.action}
          onChange={(e) => { onChange({ ...rule, action: e.target.value }); }}
          className="text-[10px] border border-border rounded px-1.5 py-1 bg-background w-20"
        >
          <option value="block">block</option><option value="mask">mask</option><option value="pass">pass</option>
        </select>
        <button onClick={onRemove} className="text-muted-foreground hover:text-red-500 shrink-0" title="Remove"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <ParamInput label="pattern" value={rule.pattern} onChange={(v) => { onChange({ ...rule, pattern: v }); }} />
      <ParamInput label="message" value={rule.message} onChange={(v) => { onChange({ ...rule, message: v }); }} />
    </div>
  );
}
