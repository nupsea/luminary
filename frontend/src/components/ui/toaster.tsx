import { Toaster as Sonner } from "sonner"

// Unstyled, so a toast is a raised surface with a status mark rather than sonner's bright fills.
export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            "flex w-full items-start gap-2.5 rounded-lg border border-hairline bg-raised p-3 text-ui text-ink-1 shadow-overlay [&_[data-icon]]:mt-0.5 [&_[data-icon]_svg]:size-4",
          title: "font-medium",
          description: "mt-0.5 text-ink-2",
          actionButton: "ml-auto h-7 shrink-0 rounded-md bg-action px-2.5 font-medium text-action-fg",
          cancelButton: "ml-auto h-7 shrink-0 rounded-md px-2.5 text-ink-2 hover:bg-hover",
          closeButton: "text-ink-2 hover:text-ink-1",
          success: "[&_[data-icon]]:text-positive",
          error: "[&_[data-icon]]:text-negative",
          warning: "[&_[data-icon]]:text-caution",
          info: "[&_[data-icon]]:text-info",
        },
      }}
    />
  )
}
