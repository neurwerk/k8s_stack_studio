interface ParamInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  maxLen?: number;
  placeholder?: string;
}

export function ParamInput({ label, value, onChange, maxLen, placeholder }: ParamInputProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-muted-foreground w-[80px] shrink-0">{label}</span>
      <input
        type="text"
        value={value}
        maxLength={maxLen}
        onChange={(e) => { onChange(e.target.value); }}
        placeholder={placeholder}
        className="text-[10px] border border-border rounded px-1.5 py-1 bg-background flex-1 font-mono"
      />
    </div>
  );
}
