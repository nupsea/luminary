import { GitBranch, Shapes } from "lucide-react"
import { MERMAID_TEMPLATES } from "@/lib/mermaidNotes"

interface MermaidQuickInsertProps {
  onInsert: (markdown: string) => void
  onDraw: () => void
}

export function MermaidQuickInsert({ onInsert, onDraw }: MermaidQuickInsertProps) {
  return (
    <>
      <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
        <GitBranch size={10} />
        Mermaid:
      </span>
      {MERMAID_TEMPLATES.map((template) => (
        <button
          key={template.label}
          type="button"
          onClick={() => onInsert(template.markdown)}
          className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium text-foreground hover:bg-accent"
        >
          {template.label}
        </button>
      ))}
      <button
        type="button"
        onClick={onDraw}
        className="flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium text-foreground hover:bg-accent"
      >
        <Shapes size={10} />
        Draw
      </button>
    </>
  )
}
