import { Loader2, type LucideIcon } from "lucide-react"

export function StartButton({
  testId,
  icon: Icon,
  label,
  hint,
  busy,
  disabled,
  onClick,
}: {
  testId: string
  icon: LucideIcon
  label: string
  hint: string
  busy: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      className="flex flex-col items-start gap-1 rounded-lg border border-border bg-background px-4 py-3 text-left transition-colors hover:border-primary hover:bg-muted/50 disabled:opacity-50"
    >
      <span className="flex items-center gap-2 text-sm font-medium text-foreground">
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
        {label}
      </span>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </button>
  )
}
