/**
 * CollectionHealthPanel -- Sheet showing health metrics for a single collection.
 *
 * Sections:
 *   Cohesion pill      -- green (>=0.7) / yellow (>=0.5) / red (<0.5) / null (< 6 notes)
 *   Uncovered Notes    -- list + "Generate Flashcards" button
 *   Stale Notes        -- list + "Archive" button
 *   Orphaned Notes     -- library-wide count + "Review" button
 *
 * Data: GET /collections/{id}/health
 * Archive action: POST /collections/{id}/health/archive-stale
 */

import { useCallback, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2, BookOpen, Clock, Archive, Eye } from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"
import { GenerateFlashcardsDialog } from "@/components/GenerateFlashcardsDialog"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UncoveredNote {
  note_id: string
  preview: string
}

interface StaleNote {
  note_id: string
  preview: string
  last_updated: string
}

interface HotspotTag {
  tag: string
  count: number
}

interface CollectionHealthReport {
  collection_id: string
  collection_name: string
  cohesion_score: number | null
  note_count: number
  orphaned_notes: string[]
  uncovered_notes: UncoveredNote[]
  stale_notes: StaleNote[]
  hotspot_tags: HotspotTag[]
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchCollectionHealth(id: string): Promise<CollectionHealthReport> {
  const res = await fetch(`${API_BASE}/collections/${id}/health`)
  if (!res.ok) throw new Error(`GET /collections/${id}/health failed: ${res.status}`)
  return res.json() as Promise<CollectionHealthReport>
}

async function archiveStaleNotes(id: string): Promise<{ archived: number }> {
  const res = await fetch(`${API_BASE}/collections/${id}/health/archive-stale`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`POST /collections/${id}/health/archive-stale failed: ${res.status}`)
  return res.json() as Promise<{ archived: number }>
}

// ---------------------------------------------------------------------------
// Cohesion pill
// ---------------------------------------------------------------------------

function CohesionPill({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-muted text-muted-foreground">
        Not enough notes
      </span>
    )
  }
  const pct = Math.round(score * 100)
  let colorClass = "bg-red-100 text-red-700"
  if (score >= 0.7) colorClass = "bg-green-100 text-green-700"
  else if (score >= 0.5) colorClass = "bg-yellow-100 text-yellow-700"

  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${colorClass}`}>
      {pct}%
    </span>
  )
}

// ---------------------------------------------------------------------------
// CollectionHealthPanel
// ---------------------------------------------------------------------------

interface CollectionHealthPanelProps {
  open: boolean
  collectionId: string | null
  onClose: () => void
}

export function CollectionHealthPanel({
  open,
  collectionId,
  onClose,
}: CollectionHealthPanelProps) {
  const qc = useQueryClient()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [generateNoteIds, setGenerateNoteIds] = useState<string[]>([])
  const [archiveMessage, setArchiveMessage] = useState<string | null>(null)

  // Navigate to Notes tab (cross-tab navigation per I-11)
  const handleReviewOrphaned = useCallback(() => {
    // Dispatch luminary:navigate event to switch to Notes tab
    window.dispatchEvent(
      new CustomEvent("luminary:navigate", { detail: { tab: "notes" } })
    )
    onClose()
  }, [onClose])

  const {
    data,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["collection-health", collectionId],
    queryFn: () => fetchCollectionHealth(collectionId!),
    enabled: open && !!collectionId,
    staleTime: 0,
  })

  const archiveMut = useMutation({
    mutationFn: () => archiveStaleNotes(collectionId!),
    onSuccess: (result) => {
      setArchiveMessage(`Archived ${result.archived} note${result.archived !== 1 ? "s" : ""}`)
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["collection-health", collectionId] })
    },
  })

  function handleGenerateFromUncovered(noteIds: string[]) {
    setGenerateNoteIds(noteIds)
    setGenerateOpen(true)
  }

  return (
    <>
      <Sheet open={open} onOpenChange={(o) => { if (!o) { setArchiveMessage(null); onClose() } }}>
        <SheetContent className="w-[420px] sm:w-[520px] overflow-y-auto">
          <SheetHeader>
            <SheetTitle>
              Collection Health
              {data && (
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  {data.collection_name}
                </span>
              )}
            </SheetTitle>
          </SheetHeader>

          {isLoading && (
            <div className="flex flex-col gap-4 mt-6">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full rounded" />
              ))}
            </div>
          )}

          {isError && (
            <div className="mt-6 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Failed to load health report. Please try again.
            </div>
          )}

          {data && (
            <div className="flex flex-col gap-5 mt-6">
              {/* Cohesion */}
              <section className="rounded-lg border border-border p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold">Cohesion Score</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Mean pairwise similarity of note vectors
                    </p>
                  </div>
                  <CohesionPill score={data.cohesion_score} />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {data.note_count} note{data.note_count !== 1 ? "s" : ""} in collection
                  {data.cohesion_score === null && data.note_count < 6
                    ? " -- needs at least 6 to compute cohesion"
                    : ""}
                </p>
              </section>

              {/* Uncovered notes */}
              <section className="rounded-lg border border-border p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <BookOpen size={14} className="text-muted-foreground" />
                    <p className="text-sm font-semibold">
                      Uncovered Notes
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        ({data.uncovered_notes.length})
                      </span>
                    </p>
                  </div>
                  {data.uncovered_notes.length > 0 && (
                    <button
                      onClick={() => handleGenerateFromUncovered(data.uncovered_notes.map((n) => n.note_id))}
                      className="rounded border border-primary/40 bg-primary/5 px-2.5 py-1 text-xs text-primary hover:bg-primary/10"
                    >
                      Generate Flashcards
                    </button>
                  )}
                </div>
                {data.uncovered_notes.length === 0 ? (
                  <p className="text-xs text-muted-foreground">All notes have flashcard coverage</p>
                ) : (
                  <ul className="flex flex-col gap-1.5 max-h-40 overflow-y-auto">
                    {data.uncovered_notes.slice(0, 10).map((n) => (
                      <li key={n.note_id} className="text-xs text-muted-foreground truncate rounded bg-muted/40 px-2 py-1">
                        {n.preview || "(empty)"}
                      </li>
                    ))}
                    {data.uncovered_notes.length > 10 && (
                      <li className="text-xs text-muted-foreground px-2">
                        +{data.uncovered_notes.length - 10} more
                      </li>
                    )}
                  </ul>
                )}
              </section>

              {/* Stale notes */}
              <section className="rounded-lg border border-border p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Clock size={14} className="text-muted-foreground" />
                    <p className="text-sm font-semibold">
                      Stale Notes
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        (not edited in 90+ days, {data.stale_notes.length})
                      </span>
                    </p>
                  </div>
                  {data.stale_notes.length > 0 && !archiveMessage && (
                    <button
                      onClick={() => archiveMut.mutate()}
                      disabled={archiveMut.isPending}
                      className="flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                    >
                      {archiveMut.isPending ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Archive size={11} />
                      )}
                      Archive
                    </button>
                  )}
                  {archiveMessage && (
                    <span className="text-xs text-green-700">{archiveMessage}</span>
                  )}
                </div>
                {data.stale_notes.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No stale notes</p>
                ) : (
                  <ul className="flex flex-col gap-1.5 max-h-40 overflow-y-auto">
                    {data.stale_notes.slice(0, 10).map((n) => (
                      <li key={n.note_id} className="text-xs text-muted-foreground rounded bg-muted/40 px-2 py-1">
                        <span className="truncate block">{n.preview || "(empty)"}</span>
                        <span className="text-muted-foreground/60">
                          Last updated: {new Date(n.last_updated).toLocaleDateString()}
                        </span>
                      </li>
                    ))}
                    {data.stale_notes.length > 10 && (
                      <li className="text-xs text-muted-foreground px-2">
                        +{data.stale_notes.length - 10} more
                      </li>
                    )}
                  </ul>
                )}
              </section>

              {/* Orphaned notes */}
              <section className="rounded-lg border border-border p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Eye size={14} className="text-muted-foreground" />
                    <p className="text-sm font-semibold">
                      Orphaned Notes
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        (library-wide, {data.orphaned_notes.length})
                      </span>
                    </p>
                  </div>
                  {data.orphaned_notes.length > 0 && (
                    <button
                      onClick={handleReviewOrphaned}
                      className="rounded border border-border bg-muted/40 px-2.5 py-1 text-xs text-foreground hover:bg-accent"
                    >
                      Review
                    </button>
                  )}
                </div>
                {data.orphaned_notes.length === 0 ? (
                  <p className="text-xs text-muted-foreground">All notes belong to a collection</p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {data.orphaned_notes.length} note{data.orphaned_notes.length !== 1 ? "s" : ""} in your library are not assigned to any collection.
                  </p>
                )}
              </section>

              {/* Hotspot tags */}
              {data.hotspot_tags.length > 0 && (
                <section className="rounded-lg border border-border p-4">
                  <p className="text-sm font-semibold mb-2">Top Tags</p>
                  <div className="flex flex-wrap gap-1.5">
                    {data.hotspot_tags.map((ht) => (
                      <span
                        key={ht.tag}
                        className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                      >
                        {ht.tag}
                        <span className="font-medium text-foreground">{ht.count}</span>
                      </span>
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>

      {/* Generate flashcards dialog pre-populated with uncovered note IDs */}
      <GenerateFlashcardsDialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        availableTags={[]}
        initialNoteIds={generateNoteIds}
      />
    </>
  )
}
