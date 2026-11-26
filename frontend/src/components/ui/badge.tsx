import { cn } from "@/lib/utils"

export type BadgeVariant = "neutral" | "brand" | "info" | "positive" | "negative" | "caution"

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  neutral: "bg-sunken text-ink-2 ring-1 ring-inset ring-hairline",
  brand: "bg-sunken text-brand ring-1 ring-inset ring-hairline",
  info: "bg-info-soft text-info-fg",
  positive: "bg-positive-soft text-positive-fg",
  negative: "bg-negative-soft text-negative-fg",
  caution: "bg-caution-soft text-caution-fg",
}

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
  children: React.ReactNode
}

export function Badge({ variant = "neutral", className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-sm px-1.5 text-caption font-medium",
        VARIANT_CLASSES[variant],
        className,
      )}
      {...props}
    >
      {children}
    </span>
  )
}
