import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Kbd } from "./kbd"
import { Tooltip } from "./tooltip"

const buttonVariants = cva(
  "inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-action font-semibold text-action-fg hover:bg-action/90",
        secondary: "border border-hairline bg-raised text-ink-1 hover:border-line-strong hover:bg-hover",
        ghost: "text-ink-2 hover:bg-hover hover:text-ink-1",
        danger: "bg-danger font-semibold text-danger-fg hover:bg-danger/90",
      },
      size: {
        sm: "h-8 px-3 text-ui",
        md: "h-9 px-4 text-body",
      },
    },
    defaultVariants: { variant: "secondary", size: "sm" },
  },
)

type ButtonVariantProps = VariantProps<typeof buttonVariants>

interface ButtonProps extends React.ComponentProps<"button">, ButtonVariantProps {
  /** A keyboard shortcut shown after the label, e.g. "Enter". */
  kbd?: string
}

export function Button({ variant, size, kbd, className, type = "button", children, ...props }: ButtonProps) {
  return (
    <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props}>
      {children}
      {kbd && <Kbd aria-hidden>{kbd}</Kbd>}
    </button>
  )
}

const ICON_SIZE = { sm: "w-8 px-0", md: "w-9 px-0" } as const

interface IconButtonProps extends Omit<React.ComponentProps<"button">, "aria-label">, ButtonVariantProps {
  /** Required: an icon-only control is otherwise unnamed to a screen reader. Also its tooltip. */
  label: string
  /** Set false where a visible label beside the button already says the same thing. */
  tooltip?: boolean
}

export function IconButton({
  label,
  tooltip = true,
  variant = "ghost",
  size = "sm",
  className,
  type = "button",
  ...props
}: IconButtonProps) {
  const button = (
    <button
      type={type}
      aria-label={label}
      className={cn(buttonVariants({ variant, size }), ICON_SIZE[size ?? "sm"], className)}
      {...props}
    />
  )
  return tooltip ? <Tooltip content={label}>{button}</Tooltip> : button
}
