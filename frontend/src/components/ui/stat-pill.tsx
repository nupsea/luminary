import { cn } from "@/lib/utils"
import { Tooltip } from "./tooltip"

const DOT = { action: "bg-action", positive: "bg-positive", negative: "bg-negative", caution: "bg-caution" } as const

interface StatPillProps {
  value: React.ReactNode
  label: string
  tone?: keyof typeof DOT
  tip?: React.ReactNode
  className?: string
}

/** A count and what it counts, e.g. "91 due". A tip makes it focusable so the keyboard reaches it. */
export function StatPill({ value, label, tone, tip, className }: StatPillProps) {
  return (
    <Tooltip content={tip}>
      <span
        tabIndex={tip ? 0 : undefined}
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-full border border-hairline px-2.5 text-ui",
          className,
        )}
      >
        {tone && <span aria-hidden className={cn("size-1.5 rounded-full", DOT[tone])} />}
        <span className="font-semibold tabular-nums text-ink-1">{value}</span>
        <span className="text-ink-2">{label}</span>
      </span>
    </Tooltip>
  )
}
