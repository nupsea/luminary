// Shared Recharts tooltip. Recharts' defaults are a white box (#fff / 1px #ccc)
// with black "name : value" text -- they ignore the design tokens and stay white
// in dark mode. This renders our popover chrome (tokens, so it flips with .dark
// for free) and inverts the default hierarchy: the value leads in strong ink,
// the series name follows, and identity comes from a short stroke of the series
// colour rather than from colouring the text.
//
// Drop-in for <Tooltip/>: <ChartTooltip /> takes the same props, so callers keep
// their existing formatter / labelFormatter.

import { Tooltip } from "recharts"
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent"
import type { TooltipContentProps, TooltipProps } from "recharts/types/component/Tooltip"

function ChartTooltipContent({
  active,
  payload,
  label,
  formatter,
  labelFormatter,
}: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null

  const heading = labelFormatter ? labelFormatter(label, payload) : label

  return (
    <div className="rounded-lg border border-border bg-popover/95 px-3 py-2 shadow-xl backdrop-blur-sm">
      {heading != null && heading !== "" && (
        <div className="mb-1.5 text-xs font-medium text-popover-foreground">{heading}</div>
      )}
      <div className="flex flex-col gap-1">
        {payload.map((entry, i) => {
          // A formatter may return the value alone or a [value, name] pair.
          const formatted = formatter
            ? formatter(entry.value, entry.name, entry, i, payload)
            : entry.value
          const [value, name] = Array.isArray(formatted)
            ? [formatted[0], formatted[1]]
            : [formatted, entry.name]
          return (
            <div key={i} className="flex items-baseline gap-2 text-xs">
              <span
                className="h-0.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              <span className="font-semibold tabular-nums text-popover-foreground">
                {value ?? "—"}
              </span>
              {name != null && name !== "" && <span className="text-muted-foreground">{name}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function ChartTooltip(props: TooltipProps<ValueType, NameType>) {
  return (
    <Tooltip
      content={ChartTooltipContent}
      // Recharts' default cursor band ignores the tokens too.
      cursor={{ fill: "hsl(var(--muted))", fillOpacity: 0.4 }}
      wrapperStyle={{ outline: "none" }}
      {...props}
    />
  )
}
