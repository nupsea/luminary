import { useState, type ReactNode } from "react"
import { Laptop, Monitor } from "lucide-react"
import { isMacPlatform } from "@/lib/keyboard"
import { cn } from "@/lib/utils"
import { noteShortcutSections, type ShortcutSurface } from "./shortcutSections"

/** The shortcut list with its platform switch; the dialog and the composer frame it. */
export function NoteShortcuts({
  surface,
  heading,
  compact = false,
}: {
  surface: ShortcutSurface
  heading: ReactNode
  compact?: boolean
}) {
  const [activeOs, setActiveOs] = useState<"mac" | "win">(() => (isMacPlatform() ? "mac" : "win"))
  const isMac = activeOs === "mac"
  const sections = noteShortcutSections(isMac, surface)

  const osButton = (os: "mac" | "win", icon: ReactNode, label: string) => (
    <button
      type="button"
      onClick={() => setActiveOs(os)}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-0.5 font-medium transition-colors",
        activeOs === os ? "bg-background text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className={cn("flex shrink-0 items-center justify-between gap-3", compact ? "pb-2" : "pb-3")}>
        {heading}
        <div className="flex items-center rounded-md border border-border bg-muted/40 p-0.5 text-[11px]">
          {osButton("mac", <Laptop className="h-3 w-3" />, "macOS")}
          {osButton("win", <Monitor className="h-3 w-3" />, compact ? "Win / Linux" : "Windows / Linux")}
        </div>
      </div>

      <div className={cn("min-h-0 flex-1 overflow-y-auto pr-1 text-sm", compact ? "space-y-3" : "space-y-5")}>
        {sections.map((section) => (
          <div key={section.title} className="space-y-1.5">
            <h3 className="px-1 text-[11px] font-bold uppercase tracking-wider text-muted-foreground/80">
              {section.title}
            </h3>
            <div className="divide-y divide-border/50 rounded-lg border border-border/60 bg-muted/20 px-3 py-1">
              {section.items.map((item) => (
                <div key={item.description} className="flex items-center justify-between gap-4 py-2 text-xs">
                  <div className="min-w-0 flex-1">
                    <span className="font-medium text-foreground">{item.description}</span>
                    {item.detail && <p className="mt-0.5 text-[11px] text-muted-foreground">{item.detail}</p>}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {item.keys.map((key) => (
                      <kbd
                        key={key}
                        className="inline-flex min-w-[20px] items-center justify-center rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[11px] font-medium text-foreground shadow-xs"
                      >
                        {key}
                      </kbd>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
