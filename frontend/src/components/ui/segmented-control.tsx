import { arrowDelta, isArrowKey } from "@/lib/keyboard"
import { cn } from "@/lib/utils"
import { Tooltip } from "./tooltip"

export interface SegmentOption<T extends string> {
  value: T
  label: React.ReactNode
  tip?: React.ReactNode
}

interface SegmentedControlProps<T extends string> {
  label: string
  value: T
  options: SegmentOption<T>[]
  onChange: (value: T) => void
  className?: string
}

/** A radio group drawn as one control: Tab enters at the selection, arrows move and select. */
export function SegmentedControl<T extends string>({ label, value, options, onChange, className }: SegmentedControlProps<T>) {
  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!isArrowKey(e.key)) return
    e.preventDefault()
    const next = (index + arrowDelta(e.key) + options.length) % options.length
    onChange(options[next].value)
    const radios = e.currentTarget.closest("[role=radiogroup]")?.querySelectorAll<HTMLElement>("[role=radio]")
    radios?.[next]?.focus()
  }

  // With no option selected, the first one still takes Tab, or the group is unreachable.
  const tabStop = options.some((o) => o.value === value) ? value : options[0]?.value

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn("inline-flex rounded-lg border border-hairline bg-rail p-0.5", className)}
    >
      {options.map((o, i) => {
        const checked = o.value === value
        return (
          <Tooltip key={o.value} content={o.tip}>
            <button
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={o.value === tabStop ? 0 : -1}
              onClick={() => onChange(o.value)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={cn(
                "inline-flex h-7 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 text-ui font-medium transition-colors [&_svg]:size-3.5",
                checked ? "bg-raised text-ink-1 shadow-sm ring-1 ring-inset ring-line-strong" : "text-ink-2 hover:text-ink-1",
              )}
            >
              {o.label}
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}
