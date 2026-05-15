// DocPicker -- compact pill <select> for choosing the active
// standalone document on the Study page. Pure presentation; the
// caller owns the active doc id.

import { BookOpen } from "lucide-react"

import type { DocListItem } from "./types"

interface DocPickerProps {
  docs: DocListItem[]
  activeId: string | null
  onSelect: (id: string | null) => void
}

export function DocPicker({ docs, activeId, onSelect }: DocPickerProps) {
  return (
    <div className="flex items-center gap-2">
      <BookOpen size={16} className="text-muted-foreground" />
      <select
        value={activeId || ""}
        onChange={(e) => onSelect(e.target.value || null)}
        className="h-9 min-w-[200px] rounded-full border border-border bg-card px-4 py-1.5 text-xs font-bold uppercase tracking-wider text-foreground transition-all hover:border-primary/50 focus:border-primary focus:outline-none"
      >
        <option value="">- SELECT STANDALONE DOC -</option>
        {docs.map((d) => (
          <option key={d.id} value={d.id}>
            {d.title.toUpperCase()}
          </option>
        ))}
      </select>
    </div>
  )
}
