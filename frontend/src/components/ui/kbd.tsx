import { cn } from "@/lib/utils"

export function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-current px-1 font-mono text-caption font-normal leading-none opacity-60",
        className,
      )}
      {...props}
    />
  )
}
