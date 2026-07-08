// FlashcardManager -- the deck-management surface for a single
// standalone document on the Study page. Owns:
//   - paginated flashcard search (hooked up to fetchFlashcardSearch)
//   - selection mode + bulk delete + delete-all
//   - 4 generate-mutations (basic / technical / graph / cloze) routed
//     through GenerateButton
//   - the "Ready to Study" hero + per-document SessionHistory tail
//   - audit-#143 section filter banner consumed once on mount from
//     the studySectionFilter zustand value (set by ChapterGoals' Study
//     button in DocumentReader).
//
// Extracted from pages/Study.tsx. The Study
// page now treats this as a black-box per-document panel with three
// callbacks: documentId in, onStartStudy / onStartTeachback out.

import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, Loader2, MessageSquare, Zap } from "lucide-react"
import { toast } from "sonner"

import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { SessionHistory } from "@/components/study/SessionHistory"
import { endOpenSessionsForScope } from "@/lib/studySessionService"
import { useAppStore } from "@/store"

import {
  GenerateError,
  bulkDeleteFlashcards,
  deleteAllFlashcardsForDocument,
  deleteFlashcard,
  fetchDocList,
  fetchDocumentSections,
  fetchFlashcardSearch,
  fetchStudyStats,
  generateClozeFlashcards,
  generateFlashcards,
  generateFlashcardsFromGraph,
  generateTechnicalFlashcards,
  updateFlashcard,
} from "./api"
import { FlashcardCard } from "./FlashcardCard"
import { GenerateButton } from "./GenerateButton"
import { InsightsAccordion } from "./InsightsAccordion"
import type { DocListItem, DocumentSections, FlashcardSearchResponse } from "./types"
import { WeakAreasPanel } from "./WeakAreasPanel"

interface FlashcardManagerProps {
  documentId: string
  onStartStudy: (filters?: any) => void
  onStartTeachback: (filters?: any, resumeId?: string) => void
}

export function FlashcardManager({
  documentId,
  onStartStudy,
  onStartTeachback,
}: FlashcardManagerProps) {
  const [page, setPage] = useState(1)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBulkDelete, setConfirmBulkDelete] = useState<
    null | "selected" | "all" | "replace"
  >(null)
  // When the user clicks "Study" on a Chapter Goal in the reader,
  // DocumentReader sets `studySectionFilter` and navigates here. We consume
  // it once on mount, copy to local state, and clear the store value so
  // back-navigation away and back to /study doesn't silently re-apply it.
  const studySectionFilter = useAppStore((s) => s.studySectionFilter)
  const setStudySectionFilter = useAppStore((s) => s.setStudySectionFilter)
  const [activeSectionFilter, setActiveSectionFilter] = useState<{
    sectionId: string
    bloomLevelMin: number
  } | null>(null)
  useEffect(() => {
    if (studySectionFilter) {
      setActiveSectionFilter(studySectionFilter)
      setPage(1)
      setStudySectionFilter(null)
    }
    // run only when the store value transitions to non-null
  }, [studySectionFilter, setStudySectionFilter])
  const qc = useQueryClient()
  const { data: docList = [] } = useQuery<DocListItem[]>({
    queryKey: ["study-doc-list"],
    queryFn: fetchDocList,
  })

  const { data: stats } = useQuery({
    queryKey: ["study-stats", documentId],
    queryFn: () => fetchStudyStats(documentId),
    enabled: !!documentId,
  })

  const { data: searchResult, isLoading: cardsLoading } = useQuery<FlashcardSearchResponse>({
    queryKey: [
      "flashcards-search",
      documentId,
      page,
      activeSectionFilter?.sectionId ?? "",
      activeSectionFilter?.bloomLevelMin ?? "",
    ],
    queryFn: () =>
      fetchFlashcardSearch({
        document_id: documentId,
        section_id: activeSectionFilter?.sectionId,
        bloom_level_min: activeSectionFilter?.bloomLevelMin,
        page,
        page_size: 20,
      }),
  })

  const { data: docData } = useQuery<DocumentSections>({
    queryKey: ["document-sections", documentId],
    queryFn: () => fetchDocumentSections(documentId),
    enabled: !!documentId,
  })

  // Heading for the active section filter banner; falls back to the id if
  // the document's sections haven't loaded yet.
  const activeSectionHeading =
    activeSectionFilter && docData
      ? docData.sections.find((s) => s.id === activeSectionFilter.sectionId)?.heading ??
        activeSectionFilter.sectionId
      : null

  const cards = searchResult?.items ?? []
  const totalCards = searchResult?.total ?? 0
  const totalPages = Math.ceil(totalCards / 20)

  // Reset selection when document changes (avoids deleting wrong doc's cards)
  useEffect(() => {
    setSelectedIds(new Set())
    setSelectionMode(false)
  }, [documentId])

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAllOnPage() {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      for (const c of cards) next.add(c.id)
      return next
    })
  }

  function clearSelection() {
    setSelectedIds(new Set())
  }

  // Mutations for update, delete, generate
  const updateMutation = useMutation({
    mutationFn: (args: { id: string; data: any }) => updateFlashcard(args.id, args.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flashcards-search"] }),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteFlashcard,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flashcards-search"] }),
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: bulkDeleteFlashcards,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      qc.invalidateQueries({ queryKey: ["study-stats", documentId] })
      clearSelection()
      setSelectionMode(false)
      setConfirmBulkDelete(null)
      toast.success(`Deleted ${res.deleted} flashcard${res.deleted === 1 ? "" : "s"}`)
    },
    onError: () => toast.error("Failed to delete selected flashcards"),
  })

  const deleteAllMutation = useMutation({
    mutationFn: async () => {
      await deleteAllFlashcardsForDocument(documentId)
      // Drop any in-progress session so it can't resume with deleted cards.
      await endOpenSessionsForScope(documentId, null)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      qc.invalidateQueries({ queryKey: ["study-stats", documentId] })
      clearSelection()
      setSelectionMode(false)
      setConfirmBulkDelete(null)
      toast.success("All flashcards deleted for this document")
    },
    onError: () => toast.error("Failed to delete flashcards"),
  })

  // Regenerate (replace): delete the current cards, then generate a fresh set of
  // the same size. A clean slate -- the old cards and their review history go.
  const replaceMutation = useMutation({
    mutationFn: async () => {
      await deleteAllFlashcardsForDocument(documentId)
      // Fresh cards -> fresh review: drop the stale in-progress session.
      await endOpenSessionsForScope(documentId, null)
      const count = Math.min(Math.max(totalCards || 10, 1), 50)
      return generateFlashcards({
        document_id: documentId,
        scope: "full",
        section_heading: null,
        count,
        difficulty: "medium",
      })
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      qc.invalidateQueries({ queryKey: ["study-stats", documentId] })
      clearSelection()
      setSelectionMode(false)
      setConfirmBulkDelete(null)
      setPage(1)
      toast.success(
        `Replaced with ${created.length} fresh card${created.length === 1 ? "" : "s"}`,
      )
    },
    onError: (err: Error) => {
      const msg =
        err instanceof GenerateError && err.status === 503
          ? "Ollama is unavailable. Start it with: ollama serve"
          : "Failed to regenerate cards"
      toast.error(msg)
    },
  })

  const generateMutation = useMutation({
    mutationFn: generateFlashcards,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success("Cards generated successfully")
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate cards"
      toast.error(msg)
    },
  })

  const generateTechnicalMutation = useMutation({
    mutationFn: generateTechnicalFlashcards,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success("Technical cards generated successfully")
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate technical cards"
      toast.error(msg)
    },
  })

  const generateGraphMutation = useMutation({
    mutationFn: ({ documentId: did, k }: { documentId: string; k: number }) =>
      generateFlashcardsFromGraph(did, k),
    onSuccess: (cards) => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success(
        cards.length > 0
          ? `Generated ${cards.length} graph card${cards.length === 1 ? "" : "s"}`
          : "No graph relationships found for this document",
      )
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate graph flashcards"
      toast.error(msg)
    },
  })

  const generateClozeMutation = useMutation({
    mutationFn: ({ sectionId, count }: { sectionId: string; count: number }) =>
      generateClozeFlashcards(sectionId, count),
    onSuccess: (cards) => {
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success(`Generated ${cards.length} cloze card${cards.length === 1 ? "" : "s"}`)
    },
    onError: (err: Error) => {
      const msg = err instanceof GenerateError && err.status === 503
        ? "Ollama is unavailable. Start it with: ollama serve"
        : "Failed to generate cloze flashcards"
      toast.error(msg)
    },
  })

  // Hero card subtitle: branch on (due, new, zero, no cards)
  function heroSubtitle(): string {
    if (!stats) return ""
    const due = stats.due_today ?? 0
    const newCount = stats.new_today ?? 0
    if (due > 0 && newCount > 0) {
      return `${due} due for review and ${newCount} new card${newCount === 1 ? "" : "s"} to learn today.`
    }
    if (due > 0) {
      return `You have ${due} flashcard${due === 1 ? "" : "s"} due for review today.`
    }
    if (newCount > 0) {
      return `${newCount} new card${newCount === 1 ? "" : "s"} ready to learn.`
    }
    if (totalCards > 0) {
      return "You're all caught up. Practice early or generate more cards."
    }
    return "No flashcards yet. Generate some to begin."
  }

  const dueOrNew = (stats?.due_today ?? 0) > 0 || (stats?.new_today ?? 0) > 0
  const showHero = !!stats || totalCards > 0
  const heroAccent = dueOrNew
    ? "from-primary/20 to-secondary/10"
    : totalCards > 0
      ? "from-emerald-500/15 to-emerald-500/5"
      : "from-muted to-muted/40"

  return (
    <div className="flex flex-col gap-8">
      {/* section filter banner -- visible when the user arrived here
          via "Study" on a Chapter Goal. Dismissing clears the filter and
          restores the unfiltered deck. */}
      {activeSectionFilter && (
        <div className="flex items-center gap-3 rounded-md border border-primary/30 bg-primary/5 px-4 py-2.5 text-sm">
          <span className="text-foreground">
            Showing cards from{" "}
            <span className="font-semibold">{activeSectionHeading ?? "this section"}</span>
            {" — Bloom level ≥ "}
            {activeSectionFilter.bloomLevelMin}
          </span>
          <button
            onClick={() => {
              setActiveSectionFilter(null)
              setPage(1)
            }}
            className="ml-auto rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            Clear filter
          </button>
        </div>
      )}
      {/* Ready to Study hero — always visible when we have stats or cards */}
      {showHero && (
         <Card className={`relative overflow-hidden border-none bg-gradient-to-br ${heroAccent} p-8 shadow-2xl transition-all`}>
            <div className="flex flex-col gap-6">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-2xl font-bold text-foreground">
                    {dueOrNew ? "Ready to Study" : totalCards > 0 ? "All Caught Up" : "No Cards Yet"}
                  </h2>
                  <p className="text-muted-foreground">{heroSubtitle()}</p>
                </div>
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/20 text-primary">
                  <Zap size={24} />
                </div>
              </div>

              {stats && (
                <div className="flex gap-4">
                  <div className="rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                    <p className="text-xs text-muted-foreground uppercase">New</p>
                    <p className="text-lg font-bold text-foreground">{stats.new_today ?? 0}</p>
                  </div>
                  <div className="rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                    <p className="text-xs text-muted-foreground uppercase">Review</p>
                    <p className="text-lg font-bold text-foreground">{stats.due_today ?? 0}</p>
                  </div>
                  <div className="flex-1 rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                    <div className="flex justify-between mb-1">
                      <p className="text-xs text-muted-foreground uppercase">Mastery</p>
                      <p className="text-xs font-bold text-foreground">{stats.mastery_pct ?? 0}%</p>
                    </div>
                    <Progress value={stats.mastery_pct ?? 0} className="h-1.5" />
                  </div>
                </div>
              )}

              {totalCards > 0 && (
                <div className="flex gap-3">
                  <button
                    onClick={() => onStartStudy({ document_id: documentId })}
                    disabled={!dueOrNew}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-blue-600 py-4 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition-all hover:bg-blue-700 hover:shadow-xl active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none"
                  >
                    <Zap size={18} />
                    {dueOrNew ? "Flashcard Review" : "Nothing Due"}
                  </button>
                  <button
                    onClick={() => onStartTeachback({ document_id: documentId })}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-violet-600 py-4 text-sm font-semibold text-white shadow-lg shadow-violet-600/20 transition-all hover:bg-violet-700 hover:shadow-xl active:scale-[0.98]"
                  >
                    <MessageSquare size={18} />
                    Teach-back Session
                  </button>
                </div>
              )}
            </div>
            {/* Subtle glow effect */}
            <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-primary/10 blur-[100px]" />
         </Card>
      )}

      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="flex flex-col gap-1">
          <h2 className="text-2xl font-bold tracking-tight text-foreground">
            {docList.find(d => d.id === documentId)?.title || "Source Grounding"}
          </h2>
          <p className="text-sm text-muted-foreground">Managing {totalCards} flashcards for this document</p>
        </div>

        <GenerateButton
          documentId={documentId}
          sections={docData?.sections || []}
          cards={cards}
          onGenerate={(req) => generateMutation.mutate({ ...req, document_id: documentId })}
          onGenerateFromGraph={(k) => generateGraphMutation.mutate({ documentId, k })}
          onGenerateCloze={(sectionId, count) =>
            generateClozeMutation.mutate({ sectionId, count })
          }
          onGenerateTechnical={(req) =>
            generateTechnicalMutation.mutate({ ...req, document_id: documentId })
          }
          isGenerating={
            generateMutation.isPending ||
            generateTechnicalMutation.isPending ||
            generateGraphMutation.isPending
          }
          isClozeGenerating={generateClozeMutation.isPending}
        />
      </div>

      {/* Bulk selection toolbar */}
      {totalCards > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-muted/30 px-4 py-2 text-sm">
          {!selectionMode ? (
            <button
              onClick={() => setSelectionMode(true)}
              className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
            >
              Select cards
            </button>
          ) : (
            <>
              <span className="text-xs font-medium text-muted-foreground">
                {selectedIds.size} selected
              </span>
              <button
                onClick={selectAllOnPage}
                className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Select all on page
              </button>
              <button
                onClick={clearSelection}
                className="rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Clear
              </button>
              <button
                onClick={() => setConfirmBulkDelete("selected")}
                disabled={selectedIds.size === 0 || bulkDeleteMutation.isPending}
                className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                Delete selected ({selectedIds.size})
              </button>
              <button
                onClick={() => {
                  setSelectionMode(false)
                  clearSelection()
                }}
                className="ml-auto rounded border border-border bg-background px-3 py-1 text-xs font-medium text-foreground hover:bg-accent"
              >
                Done
              </button>
            </>
          )}
          <button
            onClick={() => setConfirmBulkDelete("replace")}
            disabled={replaceMutation.isPending}
            className="ml-auto flex items-center gap-1 rounded border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-50"
          >
            {replaceMutation.isPending ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <Zap size={11} />
            )}
            Regenerate (replace)
          </button>
          <button
            onClick={() => setConfirmBulkDelete("all")}
            disabled={deleteAllMutation.isPending}
            className="rounded border border-red-300 bg-red-50 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400"
          >
            Delete all ({totalCards})
          </button>
        </div>
      )}

      {/* Bulk delete / replace confirmation */}
      {confirmBulkDelete && (() => {
        const isReplace = confirmBulkDelete === "replace"
        const busy =
          bulkDeleteMutation.isPending || deleteAllMutation.isPending || replaceMutation.isPending
        const tone = isReplace
          ? "border-primary/30 bg-primary/5 text-foreground"
          : "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200"
        return (
          <div className={`flex items-center gap-3 rounded-md border px-4 py-3 text-sm ${tone}`}>
            <AlertCircle size={16} />
            <span className="flex-1">
              {confirmBulkDelete === "selected"
                ? `Permanently delete ${selectedIds.size} selected flashcard${selectedIds.size === 1 ? "" : "s"}? This cannot be undone.`
                : isReplace
                  ? `Replace all ${totalCards} flashcard${totalCards === 1 ? "" : "s"} with a freshly generated set? This deletes the current cards and their review history.`
                  : `Permanently delete ALL ${totalCards} flashcards for this document? This cannot be undone.`}
            </span>
            <button
              onClick={() => {
                if (confirmBulkDelete === "selected") {
                  bulkDeleteMutation.mutate(Array.from(selectedIds))
                } else if (isReplace) {
                  replaceMutation.mutate()
                } else {
                  deleteAllMutation.mutate()
                }
              }}
              disabled={busy}
              className={`flex items-center gap-1 rounded px-3 py-1 text-xs font-semibold text-white disabled:opacity-50 ${
                isReplace ? "bg-primary hover:bg-primary/90" : "bg-red-600 hover:bg-red-700"
              }`}
            >
              {busy && <Loader2 size={12} className="animate-spin" />}
              {isReplace ? "Replace" : "Confirm delete"}
            </button>
            <button
              onClick={() => setConfirmBulkDelete(null)}
              className="rounded border border-border px-3 py-1 text-xs font-medium hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        )
      })()}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-4">
          {cardsLoading ? (
            <div className="flex py-10 justify-center"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>
          ) : cards.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border py-20 bg-card/10">
              <Zap size={32} className="text-muted-foreground opacity-30" />
              <p className="text-muted-foreground italic">No cards found. Generate some to get started.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {cards.map(c => (
                <FlashcardCard
                  key={c.id}
                  card={c}
                  onUpdate={(id, data) => updateMutation.mutate({ id, data })}
                  onDelete={(id) => deleteMutation.mutate(id)}
                  isUpdating={updateMutation.isPending}
                  isDeleting={deleteMutation.isPending}
                  selectionMode={selectionMode}
                  selected={selectedIds.has(c.id)}
                  onToggleSelect={toggleSelect}
                />
              ))}
            </div>
          )}

          {totalPages > 1 && (
            <div className="flex justify-center gap-2 mt-4">
              <button onClick={() => setPage(p => Math.max(1, p-1))} className="text-xs uppercase font-bold text-primary px-3 py-1 bg-secondary rounded-full hover:bg-secondary/80">Prev</button>
              <span className="text-xs font-bold flex items-center">{page} / {totalPages}</span>
              <button onClick={() => setPage(p => Math.min(totalPages, p+1))} className="text-xs uppercase font-bold text-primary px-3 py-1 bg-secondary rounded-full hover:bg-secondary/80">Next</button>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-6">
          <InsightsAccordion documentId={documentId} cards={cards} />
          <WeakAreasPanel documentId={documentId} onSelectSection={() => {}} />
        </div>
      </div>

      {/* Session history scoped to this document */}
      <SessionHistory
        scope={{ kind: "document", id: documentId }}
        onResumeTeachback={(sid) =>
          onStartTeachback({ document_id: documentId }, sid)
        }
      />
    </div>
  )
}
