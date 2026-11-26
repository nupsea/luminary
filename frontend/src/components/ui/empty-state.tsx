import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  /** One line at most: what would fill this space. */
  hint?: string
  action?: React.ReactNode
  className?: string
}

export function EmptyState({ icon: Icon, title, hint, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center gap-3 px-6 py-12 text-center", className)}>
      <span className="flex size-10 items-center justify-center rounded-lg bg-sunken text-ink-2">
        <Icon aria-hidden className="size-5" />
      </span>
      <div className="space-y-1">
        <p className="text-title font-semibold text-ink-1">{title}</p>
        {hint && <p className="text-ui text-ink-2">{hint}</p>}
      </div>
      {action}
    </div>
  )
}
