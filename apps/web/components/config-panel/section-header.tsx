interface SectionHeaderProps {
  title: string;
  icon?: React.ElementType;
  children?: React.ReactNode;
}

export function SectionHeader({ title, icon: Icon, children }: SectionHeaderProps) {
  return (
    <div className="flex items-center gap-2">
      {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
      <span className="text-xs font-medium text-foreground">{title}</span>
      {children}
    </div>
  );
}
