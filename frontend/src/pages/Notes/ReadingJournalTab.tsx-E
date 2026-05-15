// ReadingJournalTab -- secondary tab on the Notes page. Lists every
// clip the user has saved from the document reader, optionally
// grouped by document. Each row is a <ClipCard>.

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen } from "lucide-react"
import { useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"

import { ClipCard } from "./ClipCard"
import { fetchClips } from "./api"
import type { Clip, DocumentItem } from "./types"

interface ReadingJournalTabProps {
  documents: DocumentItem[]
  onConvertToNote: (clip: Clip) => void
  onCreateFlashcard: (clip: Clip) => void
  navigate: (url: string) => void
}

export function ReadingJournalTab({
  documents,
  onConvertToNote,
  onCreateFlashcard,
  navigate,
}: ReadingJournalTabProps) {
  const [groupByDoc, setGroupByDoc] = useState(false)
  const qc = useQueryClient()

  const { data: clips, isLoading, isError, refetch } = useQuery({
    queryKey: ["clips"],
    queryFn: () => fetchClips(),
  })

  const docTitleMap = Object.fromEntries(documents.map((d) => [d.id, d.title]))

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <span className="flex-1">Could not load clips</span>
        <button
          onClick={() => void refetch()}
          className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!clips || clips.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <BookOpen size={32} className="text-muted-foreground/50" />
        <p className="text-base font-medium text-foreground">No clips yet</p>
        <p className="text-sm text-muted-foreground">
          Select text in the Document Reader and click &ldquo;Clip&rdquo; to save a passage.
        </p>
      </div>
    )
  }

  function handleDeleted() {
    void qc.invalidateQueries({ queryKey: ["clips"] })
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={groupByDoc}
            onChange={(e) => setGroupByDoc(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border"
          />
          Group by document
        </label>
        <span className="ml-auto text-xs text-muted-foreground">
          {clips.length} clip{clips.length !== 1 ? "s" : ""}
        </span>
      </div>

      {groupByDoc ? (
        // Grouped view — native <details>/<summary> (no shadcn Accordion)
        (() => {
          const grouped = clips.reduce<Record<string, Clip[]>>((acc, c) => {
            const key = c.document_id
            ;(acc[key] ??= []).push(c)
            return acc
          }, {})
          return Object.entries(grouped).map(([docId, docClips]) => (
            <details key={docId} open className="rounded-lg border border-border">
              <summary className="cursor-pointer rounded-t-lg bg-muted px-3 py-2 text-sm font-medium text-foreground select-none">
                {docTitleMap[docId] ?? docId}
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  {docClips.length} clip{docClips.length !== 1 ? "s" : ""}
                </span>
              </summary>
              <div className="flex flex-col gap-2 p-2">
                {docClips.map((clip) => (
                  <ClipCard
                    key={clip.id}
                    clip={clip}
                    docTitle={docTitleMap[clip.document_id] ?? clip.document_id}
                    onDeleted={handleDeleted}
                    onConvertToNote={onConvertToNote}
                    onCreateFlashcard={onCreateFlashcard}
                    navigate={navigate}
                  />
                ))}
              </div>
            </details>
          ))
        })()
      ) : (
        // Flat list — newest first
        clips.map((clip) => (
          <ClipCard
            key={clip.id}
            clip={clip}
            docTitle={docTitleMap[clip.document_id] ?? clip.document_id}
            onDeleted={handleDeleted}
            onConvertToNote={onConvertToNote}
            onCreateFlashcard={onCreateFlashcard}
            navigate={navigate}
          />
        ))
      )}
    </div>
  )
}
