import { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Keyboard, Laptop, Monitor } from "lucide-react"
import { isMacPlatform } from "@/lib/keyboard"

export interface NoteShortcutsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface ShortcutItem {
  keys: string[]
  description: string
  detail?: string
}

interface ShortcutSection {
  title: string
  items: ShortcutItem[]
}

export function NoteShortcutsDialog({ open, onOpenChange }: NoteShortcutsDialogProps) {
  const detectedMac = isMacPlatform()
  const [activeOs, setActiveOs] = useState<"mac" | "win">(() => (detectedMac ? "mac" : "win"))

  const isMac = activeOs === "mac"
  const MOD = isMac ? "⌘" : "Ctrl"
  const ALT = isMac ? "⌥" : "Alt"
  const SHIFT = isMac ? "⇧" : "Shift"

  const sections: ShortcutSection[] = [
    {
      title: "Lists & Indentation",
      items: [
        {
          keys: ["Tab"],
          description: "Indent list item or selected lines",
          detail: "In tables: navigate to the next cell",
        },
        {
          keys: [SHIFT, "Tab"],
          description: "Dedent (outdent) list item or lines",
          detail: "In tables: navigate to previous cell",
        },
        {
          keys: ["Enter"],
          description: "Continue list item or quote",
          detail: "Auto-increments numbers (1. → 2.); press Enter again on empty item to cleanly exit list",
        },
      ],
    },
    {
      title: "Formatting & Links",
      items: [
        {
          keys: [MOD, "B"],
          description: "Bold text",
        },
        {
          keys: [MOD, "I"],
          description: "Italic text",
        },
        {
          keys: [MOD, SHIFT, "S"],
          description: "Strikethrough text",
          detail: `Also supports ${MOD} + ${SHIFT} + X`,
        },
        {
          keys: [MOD, "`"],
          description: "Inline code",
        },
        {
          keys: [MOD, "K"],
          description: "Insert or remove link",
          detail: "Wraps selection in [text](url) and highlights url for quick pasting",
        },
      ],
    },
    {
      title: "Navigation & Line Editing",
      items: [
        {
          keys: isMac ? ["⌘", "→"] : ["End"],
          description: "Jump to end of line",
          detail: isMac ? "Full keyboards can also use End" : "Moves cursor to line end without scrolling to page bottom",
        },
        {
          keys: isMac ? ["⌘", "←"] : ["Home"],
          description: "Jump to start of line / indentation",
          detail: isMac ? "Full keyboards can also use Home" : "Toggles between first text character and column 0",
        },
        {
          keys: isMac ? [SHIFT, "⌘", "→ / ←"] : [SHIFT, "End / Home"],
          description: "Select to end / start of line",
        },
        {
          keys: [ALT, "↑ / ↓"],
          description: "Move current line up or down",
        },
        {
          keys: [SHIFT, ALT, "↑ / ↓"],
          description: "Duplicate line up or down",
        },
        {
          keys: ["→ / ←"],
          description: "Step into rendered block",
          detail: "Expands rendered markdown blocks into editable source",
        },
      ],
    },
    {
      title: "Notes & Smart Triggers",
      items: [
        {
          keys: ["/"],
          description: "Slash command menu",
          detail: "Insert headings, lists, tables, callouts, drawings, or math",
        },
        {
          keys: ["[["],
          description: "Link to another note",
          detail: "Type [[ to search and link notes directly",
        },
        {
          keys: [MOD, "K"],
          description: "Insert or create note link",
          detail: "Wraps selection or triggers note link search",
        },
        {
          keys: [MOD, "E"],
          description: "Toggle reading / editing view",
        },
        {
          keys: [MOD, "S"],
          description: "Save note immediately",
          detail: "Notes autosave continuously as you type",
        },
        {
          keys: [MOD, "/"],
          description: "Open this keyboard shortcuts dialog",
        },
      ],
    },
  ]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col overflow-hidden p-6">
        <DialogHeader className="shrink-0 pb-2">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Keyboard className="h-4 w-4" />
              </div>
              <div>
                <DialogTitle className="text-base font-semibold">Note Editor Shortcuts</DialogTitle>
                <DialogDescription className="text-xs text-muted-foreground">
                  Works across macOS, Windows, Linux, Desktop App & Web
                </DialogDescription>
              </div>
            </div>

            {/* Platform switcher */}
            <div className="flex items-center rounded-md border border-border bg-muted/40 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setActiveOs("mac")}
                className={`flex items-center gap-1 rounded px-2.5 py-1 font-medium transition-colors ${
                  isMac
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Laptop className="h-3 w-3" />
                macOS
              </button>
              <button
                type="button"
                onClick={() => setActiveOs("win")}
                className={`flex items-center gap-1 rounded px-2.5 py-1 font-medium transition-colors ${
                  !isMac
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Monitor className="h-3 w-3" />
                Windows / Linux
              </button>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto pr-1 space-y-5 text-sm">
          {sections.map((section) => (
            <div key={section.title} className="space-y-2">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/80 px-1">
                {section.title}
              </h3>
              <div className="divide-y divide-border/50 rounded-lg border border-border/60 bg-muted/20 px-3 py-1">
                {section.items.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between py-2 text-xs gap-4"
                  >
                    <div className="min-w-0 flex-1">
                      <span className="font-medium text-foreground">{item.description}</span>
                      {item.detail && (
                        <p className="text-[11px] text-muted-foreground mt-0.5">{item.detail}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {item.keys.map((key, kIdx) => (
                        <kbd
                          key={kIdx}
                          className="inline-flex min-w-[20px] items-center justify-center rounded border border-border bg-background px-1.5 py-0.5 text-[11px] font-mono font-medium text-foreground shadow-xs"
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
      </DialogContent>
    </Dialog>
  )
}
