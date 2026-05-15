import { cn } from "@/lib/utils"

type BadgeVariant = "default" | "gray" | "blue" | "indigo" | "green"

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  default: "bg-secondary text-secondary-foreground",
  gray: "bg-gray-100 text-gray-700",
  blue: "bg-blue-100 text-blue-700",
  indigo: "bg-indigo-100 text-indigo-700",
  green: "bg-green-100 text-green-700",
}

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
  children: React.ReactNode
}

export function Badge({ variant = "default", className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        VARIANT_CLASSES[variant],
        className,
      )}
      {...props}
    >
      {children}
    </span>
  )
}
