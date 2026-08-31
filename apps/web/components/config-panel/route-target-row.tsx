import { Trash2 } from "lucide-react";
import type { RouteTarget } from "@/lib/config-generator";

import { ParamInput } from "./param-input";

interface RouteTargetRowProps {
  target: RouteTarget;
  onChange: (t: RouteTarget) => void;
  onRemove: () => void;
}

export function RouteTargetRow({ target, onChange, onRemove }: RouteTargetRowProps) {
  return (
    <div className="rounded border border-border bg-background p-2 space-y-1">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={target.name}
          onChange={(e) => { onChange({ ...target, name: e.target.value }); }}
          className="text-[11px] font-mono border border-border rounded px-2 py-1 bg-muted/30 flex-1"
          placeholder="target-name"
        />
        <button onClick={onRemove} className="text-muted-foreground hover:text-red-500 shrink-0" title="Remove"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <ParamInput label="model" value={target.model} onChange={(v) => { onChange({ ...target, model: v }); }} />
      <ParamInput label="provider" value={target.provider} onChange={(v) => { onChange({ ...target, provider: v }); }} />
      <ParamInput label="baseURL" value={target.baseURL} onChange={(v) => { onChange({ ...target, baseURL: v }); }} />
      <ParamInput label="when (CEL)" value={target.when} onChange={(v) => { onChange({ ...target, when: v }); }} />
      <ParamInput label="authSecret" value={target.authSecret || ""} onChange={(v) => { onChange({ ...target, authSecret: v || undefined }); }} />
    </div>
  );
}
