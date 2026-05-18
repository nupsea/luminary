// MasteryPanel -- Concept mastery heatmap + weak-spots list +
// "no flashcards yet" chips, scoped to a single document chosen via a
// header dropdown.

import { useEffect, useState } from "react"
import { toast } from "sonner"

import { logger } from "@/lib/logger"

import { fetchMasteryConcepts, fetchMasteryHeatmap } from "./api"
import {
  EmptyState,
  SectionErrorCard,
  SectionSkeleton,
} from "./SharedUI"
import type {
  Document,
  MasteryConceptsResponse,
  MasteryHeatmapResponse,
  SectionState,
} from "./types"
import { initSection } from "./types"
import { masteryColor } from "./utils"

export function MasteryPanel({ documents }: { documents: Document[] }) {
  const [selectedDocId, setSelectedDocId] = useState<string>(documents[0]?.id ?? "")
  const [conceptsState, setConceptsState] = useState<
    SectionState<MasteryConceptsResponse | null>
  >(initSection(null))
  const [heatmapState, setHeatmapState] = useState<
    SectionState<MasteryHeatmapResponse | null>
  >(initSection(null))

  // When documents load after mount (selectedDocId is ""), auto-select the first
  useEffect(() => {
    if (!selectedDocId && documents.length > 0) {
      setSelectedDocId(documents[0].id)
    }
  }, [documents, selectedDocId])

  useEffect(() => {
    if (!selectedDocId) return
    let cancelled = false
    setConceptsState(initSection(null))
    setHeatmapState(initSection(null))

    fetchMasteryConcepts([selectedDocId])
      .then((d) => {
        if (!cancelled) setConceptsState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] mastery/concepts failed", e)
        if (!cancelled) setConceptsState({ loading: false, data: null, error: true })
      })

    fetchMasteryHeatmap(selectedDocId)
      .then((d) => {
        if (!cancelled) setHeatmapState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] mastery/heatmap failed", e)
        if (!cancelled) setHeatmapState({ loading: false, data: null, error: true })
      })

    return () => {
      cancelled = true
    }
  }, [selectedDocId])

  if (documents.length === 0) {
    return <EmptyState message="No documents yet. Ingest a document to see mastery data." />
  }

  const concepts = conceptsState.data?.concepts ?? []
  const heatmap = heatmapState.data
  const weakSpots = concepts.filter((c) => c.mastery < 0.4 && c.card_count >= 1).slice(0, 5)
  const noCards = concepts.filter((c) => c.no_flashcards).slice(0, 5)

  return (
    <div className="flex flex-col gap-6">
      {/* Document selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-foreground">Document:</label>
        <select
          value={selectedDocId}
          onChange={(e) => setSelectedDocId(e.target.value)}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground"
        >
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              {d.title}
            </option>
          ))}
        </select>
      </div>

      {/* Heatmap */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Concept Mastery Heatmap</h2>
        {heatmapState.loading ? (
          <SectionSkeleton rows={4} />
        ) : heatmapState.error ? (
          <SectionErrorCard name="Mastery Heatmap" />
        ) : !heatmap || heatmap.concepts.length === 0 ? (
          <EmptyState message="No entities found for this document. Ensure the document has been enriched." />
        ) : (
          <div className="overflow-auto rounded-lg border border-border">
            <table className="border-collapse text-xs">
              <thead>
                <tr>
                  <th className="min-w-24 bg-secondary px-3 py-2 text-left text-muted-foreground">
                    Concept \ Chapter
                  </th>
                  {heatmap.chapters.map((ch) => (
                    <th
                      key={ch}
                      className="min-w-20 bg-secondary px-2 py-2 text-center text-muted-foreground"
                      title={ch}
                    >
                      {ch.length > 14 ? ch.slice(0, 12) + "…" : ch}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmap.concepts.map((concept) => (
                  <tr key={concept} className="border-t border-border">
                    <td className="px-3 py-1 font-medium text-foreground">{concept}</td>
                    {heatmap.chapters.map((chapter) => {
                      const cell = heatmap.cells.find(
                        (c) => c.chapter === chapter && c.concept === concept,
                      )
                      const mastery = cell?.mastery ?? null
                      const cardCount = cell?.card_count ?? 0
                      return (
                        <td key={chapter} className="px-1 py-1 text-center">
                          <div
                            className={`mx-auto h-6 w-12 rounded ${masteryColor(mastery)}`}
                            title={
                              mastery === null
                                ? `${concept} / ${chapter}: no flashcards`
                                : `${concept} / ${chapter}: mastery ${(mastery * 100).toFixed(0)}% (${cardCount} cards)`
                            }
                          />
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center gap-3 p-3 text-xs text-muted-foreground">
              <span>Color:</span>
              <span className="h-3 w-6 rounded bg-gray-100 dark:bg-gray-800 border" /> No cards
              <span className="h-3 w-6 rounded bg-blue-200 dark:bg-blue-900" /> &lt;30%
              <span className="h-3 w-6 rounded bg-blue-400 dark:bg-blue-700" /> 30-60%
              <span className="h-3 w-6 rounded bg-green-400 dark:bg-green-700" /> 60-80%
              <span className="h-3 w-6 rounded bg-green-600 dark:bg-green-500" /> &gt;80%
            </div>
          </div>
        )}
      </section>

      {/* Weak spots panel */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Weak Spots</h2>
        {conceptsState.loading ? (
          <SectionSkeleton rows={3} />
        ) : conceptsState.error ? (
          <SectionErrorCard name="Weak Spots" />
        ) : weakSpots.length === 0 ? (
          <EmptyState message="No weak spots. Either mastery is solid or no flashcards exist yet." />
        ) : (
          <div className="flex flex-col gap-2">
            {weakSpots.map((c) => (
              <div
                key={c.concept}
                className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3"
              >
                <span className="font-medium text-foreground">{c.concept}</span>
                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                  <span>{(c.mastery * 100).toFixed(0)}% mastery</span>
                  <span>{c.card_count} cards</span>
                  {c.due_soon > 0 && (
                    <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                      {c.due_soon} due soon
                    </span>
                  )}
                </div>
              </div>
            ))}
            <button
              onClick={() => {
                const names = weakSpots.map((c) => c.concept).join(", ")
                toast.info(`Weak spots: ${names}. Go to the Study tab to review.`)
              }}
              className="mt-1 self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Quick study weak spots
            </button>
          </div>
        )}
      </section>

      {/* No flashcards panel */}
      {noCards.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold text-foreground">No Flashcards Yet</h2>
          <div className="flex flex-wrap gap-2">
            {noCards.map((c) => (
              <span
                key={c.concept}
                className="rounded-full border border-border bg-secondary px-3 py-1 text-xs text-muted-foreground"
              >
                {c.concept}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
