// NoteConceptChips -- concept-link chips, "Quiz me on this note" and "Make cards"
// (docs/03-notes-generation.md). Reads GET /concepts/for-note/{id} (engagement +
// lexical; degrades gracefully when the linker is off). Each chip opens the Study
// Launcher on that concept; "Quiz me" opens it on the whole note.
//
// The two buttons are different verbs and the pair is deliberate: "Quiz me"
// studies cards that exist, "Make cards" writes them. Only the first was here, so
// a note with no cards yet offered nothing at the moment the reader wants them.

import { useQuery } from "@tanstack/react-query"
import { CreditCard, Sparkles, Tag } from "lucide-react"
import { useMemo, useState } from "react"

import { GenerateFlashcardsDialog } from "@/components/GenerateFlashcardsDialog"
import { apiGet } from "@/lib/apiClient"
import { launchStudy } from "@/lib/studyLauncher"

interface NoteConcept {
  id: string
  slug: string
  label: string
  kind: string
  status: string
  mastery: number
}

export function NoteConceptChips({
  noteId,
  noteTitle,
}: {
  noteId: string
  noteTitle?: string
}) {
  const [generating, setGenerating] = useState(false)
  // Stable identity: the dialog's open-effect depends on this array and calls
  // setState from it, so a fresh literal each render re-runs the effect, sets
  // state, and re-renders -- the unbounded loop InDocSearchBar hit.
  const scope = useMemo(() => [noteId], [noteId])
  const { data, isLoading } = useQuery({
    queryKey: ["note-concepts", noteId],
    queryFn: () => apiGet<NoteConcept[]>(`/concepts/for-note/${noteId}`),
    enabled: Boolean(noteId),
  })

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Tag size={12} />
          <span className="text-[10px] font-bold uppercase tracking-wider">Concepts</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setGenerating(true)}
            title="Generate flashcards from this note"
            className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <CreditCard size={10} />
            Make cards
          </button>
          <button
            onClick={() =>
              launchStudy({ type: "note", ref: noteId, label: noteTitle || "this note" })
            }
            title="Study the cards this note already has"
            className="flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-2 py-0.5 text-[11px] text-primary hover:bg-primary/10 transition-colors"
          >
            <Sparkles size={10} />
            Quiz me on this note
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {isLoading ? (
          <span className="text-xs text-muted-foreground italic">Loading…</span>
        ) : data && data.length > 0 ? (
          data.map((c) => (
            <button
              key={c.id}
              onClick={() => launchStudy({ type: "concept", ref: c.id, label: c.label })}
              title={`Study ${c.label}`}
              className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs hover:bg-accent transition-colors"
            >
              {c.label}
              {c.status !== "confirmed" && (
                <span className="text-[9px] text-muted-foreground">·{c.status}</span>
              )}
            </button>
          ))
        ) : (
          <span className="text-xs text-muted-foreground italic">No linked concepts yet</span>
        )}
      </div>
      <GenerateFlashcardsDialog
        open={generating}
        onClose={() => setGenerating(false)}
        availableTags={[]}
        initialNoteIds={scope}
      />
    </div>
  )
}
