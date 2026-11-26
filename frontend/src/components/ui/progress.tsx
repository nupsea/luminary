import { cn } from "@/lib/utils"

const TONE = { action: "bg-action", positive: "bg-positive", caution: "bg-caution" } as const

interface ProgressProps {
  value: number
  tone?: keyof typeof TONE
  label?: string
  className?: string
}

export function Progress({ value, tone = "action", label, className }: ProgressProps) {
  const pct = Math.min(100, Math.max(0, value))
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-label={label}
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-hairline", className)}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-300", TONE[tone])}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
