import { cn } from "@/lib/utils"

export function Eyebrow({ className, ...props }: React.ComponentProps<"p">) {
  return <p className={cn("text-eyebrow font-bold uppercase text-ink-2", className)} {...props} />
}

interface SectionHeadingProps extends Omit<React.ComponentProps<"div">, "title"> {
  title: React.ReactNode
  count?: number
  as?: "h2" | "h3"
  /** Controls at the right end of the heading row. */
  action?: React.ReactNode
}

export function SectionHeading({ title, count, as: Tag = "h2", action, className, ...props }: SectionHeadingProps) {
  return (
    <div className={cn("flex min-h-8 items-center justify-between gap-3", className)} {...props}>
      <Tag className="text-title font-semibold text-ink-1">
        {title}
        {count != null && <span className="ml-1.5 font-normal tabular-nums text-ink-2">{count}</span>}
      </Tag>
      {action && <div className="flex items-center gap-2">{action}</div>}
    </div>
  )
}
