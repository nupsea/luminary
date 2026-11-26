import { cn } from "@/lib/utils"
import { Tooltip } from "./tooltip"

interface ChipProps extends Omit<React.ComponentProps<"button">, "aria-pressed"> {
  selected?: boolean
  count?: number
  tip?: React.ReactNode
}

/** A filter or scope toggle. Selection is announced through aria-pressed. */
export function Chip({ selected = false, count, tip, className, type = "button", children, ...props }: ChipProps) {
  return (
    <Tooltip content={tip}>
      <button
        type={type}
        aria-pressed={selected}
        className={cn(
          "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-ui transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-3.5",
          selected
            ? "border-action bg-action text-action-fg"
            : "border-hairline bg-raised text-ink-2 hover:border-line-strong hover:text-ink-1",
          className,
        )}
        {...props}
      >
        {children}
        {count != null && <span className="tabular-nums opacity-70">{count}</span>}
      </button>
    </Tooltip>
  )
}
