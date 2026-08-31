import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { ClassifierClass } from "@/lib/config-generator";

import { PatternEditor } from "./pattern-editor";

interface ClassifierClassRowProps {
  cls: ClassifierClass;
  onChange: (c: ClassifierClass) => void;
  onRemove: () => void;
}

export function ClassifierClassRow({ cls, onChange, onRemove }: ClassifierClassRowProps) {
  const [showPatterns, setShowPatterns] = useState(cls.patterns.length > 0);
  return (
    <div className="rounded border border-border bg-background p-2 space-y-1">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={cls.name}
          onChange={(e) => { onChange({ ...cls, name: e.target.value }); }}
          className="text-[11px] font-mono border border-border rounded px-2 py-1 bg-muted/30 flex-1"
          placeholder="class-name"
        />
        <button onClick={onRemove} className="text-muted-foreground hover:text-red-500 shrink-0" title="Remove"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <button
        onClick={() => { setShowPatterns(!showPatterns); }}
        className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
      >
        <Plus className="h-3 w-3" /> {showPatterns ? "Hide" : "Edit"} patterns ({cls.patterns.length})
      </button>
      {showPatterns && <PatternEditor patterns={cls.patterns} onChange={(p) => { onChange({ ...cls, patterns: p }); }} />}
    </div>
  );
}
