import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

const FIELD =
  "w-full rounded-md border border-hairline bg-raised text-body text-ink-1 transition-colors placeholder:text-ink-2 hover:border-line-strong focus-visible:border-focus disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-danger"

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input className={cn(FIELD, "h-9 px-3", className)} {...props} />
}

export function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return <textarea className={cn(FIELD, "min-h-20 px-3 py-2", className)} {...props} />
}

/** A native select: the platform's own list, keyboard and screen-reader behaviour. */
export function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <div className={cn("relative", className)}>
      <select className={cn(FIELD, "h-9 appearance-none pl-3 pr-8")} {...props}>
        {children}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-2" />
    </div>
  )
}
