import { Plus, Trash2 } from "lucide-react";

interface PatternEditorProps {
  patterns: string[];
  onChange: (p: string[]) => void;
}

export function PatternEditor({ patterns, onChange }: PatternEditorProps) {
  return (
    <div className="ml-1 mt-1 border-l-2 border-muted-foreground/20 pl-3 space-y-1">
      {patterns.map((pat, i) => (
        <div key={i} className="flex items-center gap-1">
          <input
            type="text"
            value={pat}
            onChange={(e) => {
              const c = [...patterns]; c[i] = e.target.value; onChange(c);
            }}
            placeholder="regex pattern..."
            className="text-[10px] border border-border rounded px-1.5 py-0.5 bg-background flex-1 font-mono"
          />
          <button
            onClick={() => { onChange(patterns.filter((_, j) => j !== i)); }}
            className="text-muted-foreground hover:text-red-500 shrink-0"
            title="Remove"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      ))}
      <button
        onClick={() => { onChange([...patterns, ""]); }}
        className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
      >
        <Plus className="h-3 w-3" /> Add pattern
      </button>
    </div>
  );
}
