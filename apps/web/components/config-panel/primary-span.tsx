interface PrimarySpanProps {
  children: React.ReactNode;
  className?: string;
}

export function PrimarySpan({ children, className }: PrimarySpanProps) {
  return <span className={`text-[10px] text-muted-foreground block ${className || ""}`}>{children}</span>;
}
