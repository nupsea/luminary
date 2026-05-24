import { MERMAID_CHEAT_SHEET } from "@/lib/mermaidNotes"

interface MermaidCheatSheetProps {
  className?: string
}

export function MermaidCheatSheet({ className }: MermaidCheatSheetProps) {
  return (
    <details
      className={
        className ??
        "rounded border border-border bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground"
      }
    >
      <summary className="cursor-pointer select-none font-medium text-foreground">
        Mermaid cheat sheet
      </summary>
      <div className="mt-2 grid grid-cols-1 gap-1">
        {MERMAID_CHEAT_SHEET.map((item) => (
          <code key={item} className="rounded bg-background px-1.5 py-1 text-[10px] text-foreground">
            {item}
          </code>
        ))}
      </div>
    </details>
  )
}
