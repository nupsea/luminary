/**
 * Study tab — Flashcard section (S20b) and Progress section placeholder (S23b).
 *
 * Flashcard section:
 *  - Generate panel: count selector, scope (full/section), Generate button
 *  - Flashcard list: show/hide answer, inline edit, delete with confirmation
 *  - Bottom bar: card count, Start Studying (S21b), CSV export
 * Study session (S21b):
 *  - Full-screen StudySession replaces tab content when studying
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import {
  AlertCircle,
  BookOpen,
  ChevronRight,
  CornerDownRight,
  Layers,
  Loader2,
  MessageSquare,
  Plus,
  StickyNote,
  Zap,
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import { motion } from "framer-motion"
import { toast } from "sonner"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { useAppStore } from "@/store"
import { useEffectiveActiveDocument } from "@/hooks/useEffectiveActiveDocument"
import { isDocumentReady } from "@/lib/documentReadiness"
import {
  FLASHCARD_CARD_LIMIT,
  StudySession,
} from "@/components/StudySession"
import {
  TEACHBACK_CARD_LIMIT,
  TeachbackSession,
} from "@/components/TeachbackSession"
import { SessionManager } from "@/components/SessionManager"
import { CollectionStudyDashboard } from "@/components/study/CollectionStudyDashboard"
import { SessionHistory } from "@/components/study/SessionHistory"
import { GoalsList } from "@/components/goals/GoalsList"
import {
  type PrepareStudySessionOptions,
  type PreparedStudySessionOutcome,
  type StudyMode,
  prepareStudySession,
} from "@/lib/studySessionService"


// ---------------------------------------------------------------------------
// Document list for the in-tab picker
// ---------------------------------------------------------------------------

import { API_BASE } from "@/lib/config"

import type {
  DocListItem,
  DocumentSections,
  FlashcardSearchResponse,
} from "./Study/types"
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
} from "./Study/api"
import { DocPicker } from "./Study/DocPicker"
import { FlashcardCard } from "./Study/FlashcardCard"
import { InsightsAccordion } from "./Study/InsightsAccordion"
import { GenerateButton } from "./Study/GenerateButton"
import { WeakAreasPanel } from "./Study/WeakAreasPanel"



// ---------------------------------------------------------------------------
// (S211) Old document-centric GoalsPanel removed in favour of typed-goals UI
// in @/components/goals/GoalsList. Re-export DocListItem for Progress.tsx.
// ---------------------------------------------------------------------------

export type { DocListItem } from "./Study/types"  // re-exported for Progress.tsx

// SessionHistoryTab replaced by SessionManager component

// DocPicker now lives in pages/Study/DocPicker.tsx.

// ---------------------------------------------------------------------------
// FlashcardManager (Standalone view for document-centric study)
// ---------------------------------------------------------------------------

function FlashcardManager({
  documentId,
  onStartStudy,
  onStartTeachback,
}: {
  documentId: string;
  onStartStudy: (filters?: any) => void;
  onStartTeachback: (filters?: any, resumeId?: string) => void;
}) {
  const [page, setPage] = useState(1)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBulkDelete, setConfirmBulkDelete] = useState<null | "selected" | "all">(null)
  // S143: When the user clicks "Study" on a Chapter Goal in the reader,
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
    mutationFn: () => deleteAllFlashcardsForDocument(documentId),
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
      {/* S143: section filter banner -- visible when the user arrived here
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
            onClick={() => setConfirmBulkDelete("all")}
            disabled={deleteAllMutation.isPending}
            className="ml-auto rounded border border-red-300 bg-red-50 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400"
          >
            Delete all ({totalCards})
          </button>
        </div>
      )}

      {/* Bulk delete confirmation */}
      {confirmBulkDelete && (
        <div className="flex items-center gap-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
          <AlertCircle size={16} />
          <span className="flex-1">
            {confirmBulkDelete === "selected"
              ? `Permanently delete ${selectedIds.size} selected flashcard${selectedIds.size === 1 ? "" : "s"}? This cannot be undone.`
              : `Permanently delete ALL ${totalCards} flashcards for this document? This cannot be undone.`}
          </span>
          <button
            onClick={() => {
              if (confirmBulkDelete === "selected") {
                bulkDeleteMutation.mutate(Array.from(selectedIds))
              } else {
                deleteAllMutation.mutate()
              }
            }}
            disabled={bulkDeleteMutation.isPending || deleteAllMutation.isPending}
            className="flex items-center gap-1 rounded bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >
            {(bulkDeleteMutation.isPending || deleteAllMutation.isPending) && (
              <Loader2 size={12} className="animate-spin" />
            )}
            Confirm delete
          </button>
          <button
            onClick={() => setConfirmBulkDelete(null)}
            className="rounded border border-red-300 px-3 py-1 text-xs font-medium hover:bg-red-100 dark:hover:bg-red-900/40"
          >
            Cancel
          </button>
        </div>
      )}

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

// ---------------------------------------------------------------------------
// Study page
// ---------------------------------------------------------------------------

export default function Study() {
  const navigate = useNavigate()
  const {
    setActiveDocument,
    activeCollectionId,
    setActiveCollectionId,
  } = useAppStore()

  // Effective doc: ready-only fallback so we never feed an in-progress doc
  // into prepareStudySession or FlashcardManager. Both depend on populated
  // chunks/embeddings/flashcards, which simply don't exist mid-ingestion.
  const { doc: effectiveDoc, effectiveDocumentId, isFallingBack } =
    useEffectiveActiveDocument()
  const studyDocumentId = effectiveDocumentId

  // Study-session lifecycle lives entirely in this one state variable.
  // It is ONLY mutated by explicit user handlers (handleStartFlashcard,
  // handleStartTeachback, handleExit). Session creation happens in the
  // "preparing" phase via prepareStudySession (one user click = one call).
  type StudyPhase =
    | { phase: "idle" }
    | { phase: "preparing"; mode: StudyMode }
    | {
        phase: "ready"
        mode: StudyMode
        outcome: PreparedStudySessionOutcome
        scopeForBeginNew: PrepareStudySessionOptions
      }
  const [studyPhase, setStudyPhase] = useState<StudyPhase>({ phase: "idle" })

  const { data: collections = [], isLoading: loadingCollections } = useQuery({
    queryKey: ["collections-list"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/collections/tree`)
      if (!res.ok) return []
      return res.json() as Promise<any[]>
    },
  })

  const { data: docList = [] } = useQuery<DocListItem[]>({
    queryKey: ["study-doc-list"],
    queryFn: fetchDocList,
  })

  type StudyFiltersLike = {
    tag?: string
    document_ids?: string[]
    note_ids?: string[]
  }
  const startStudy = async (
    mode: StudyMode,
    filters: StudyFiltersLike | null,
    resumeId: string | null,
  ) => {
    // Guard: if we are already preparing or in a ready state, ignore the
    // click. This prevents a double-click (or a re-fired event from a
    // downstream component) from launching two prepareStudySession calls.
    if (studyPhase.phase !== "idle") return

    setStudyPhase({ phase: "preparing", mode })
    const options: PrepareStudySessionOptions = {
      mode,
      documentId: studyDocumentId,
      collectionId: activeCollectionId ?? null,
      filters: filters ?? undefined,
      cardLimit:
        mode === "teachback" ? TEACHBACK_CARD_LIMIT : FLASHCARD_CARD_LIMIT,
      resumeSessionId: resumeId,
    }
    try {
      const outcome = await prepareStudySession(options)
      setStudyPhase({
        phase: "ready",
        mode,
        outcome,
        scopeForBeginNew: { ...options, resumeSessionId: null },
      })
    } catch (err) {
      console.warn("Failed to prepare study session", err)
      setStudyPhase({ phase: "idle" })
      toast.error("Could not start study session. Please try again.")
    }
  }

  const handleStartFlashcard = (filters?: StudyFiltersLike) => {
    void startStudy("flashcard", filters ?? null, null)
  }

  const handleStartTeachback = (
    filters?: StudyFiltersLike,
    resumeId?: string,
  ) => {
    void startStudy("teachback", filters ?? null, resumeId ?? null)
  }

  // Walk the nested collection tree to find a name by id.
  const findCollectionName = (
    items: any[],
    id: string | null,
  ): string | null => {
    if (!id) return null
    for (const item of items) {
      if (item.id === id) return item.name ?? null
      if (item.children?.length) {
        const found = findCollectionName(item.children, id)
        if (found) return found
      }
    }
    return null
  }

  const activeDocTitle = effectiveDoc?.title ?? null
  const activeCollectionName = findCollectionName(collections, activeCollectionId)
  const subjectLabel =
    activeCollectionName || activeDocTitle || null

  const handleExit = () => {
    setStudyPhase({ phase: "idle" })
  }

  // ---- Active session routes ------------------------------------------------
  if (studyPhase.phase === "preparing") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2
          size={32}
          className={
            studyPhase.mode === "teachback"
              ? "animate-spin text-violet-500"
              : "animate-spin text-primary"
          }
        />
      </div>
    )
  }

  if (studyPhase.phase === "ready" && studyPhase.mode === "flashcard") {
    return (
      <StudySession
        initial={
          studyPhase.outcome.kind === "empty"
            ? { kind: "empty" }
            : {
                kind: studyPhase.outcome.kind,
                session: studyPhase.outcome.session,
              }
        }
        scopeForBeginNew={studyPhase.scopeForBeginNew}
        onExit={handleExit}
      />
    )
  }

  if (studyPhase.phase === "ready" && studyPhase.mode === "teachback") {
    return (
      <TeachbackSession
        initial={
          studyPhase.outcome.kind === "empty"
            ? { kind: "empty" }
            : {
                kind: studyPhase.outcome.kind,
                session: studyPhase.outcome.session,
              }
        }
        scopeForBeginNew={studyPhase.scopeForBeginNew}
        onExit={handleExit}
        subjectLabel={subjectLabel}
      />
    )
  }

  // ---- Main study dashboard -------------------------------------------------
  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-card/30 px-8 py-3 backdrop-blur-md">
        <div className="flex items-center gap-8">
          <h1
            className="cursor-pointer text-xl font-bold tracking-tight text-foreground"
            onClick={() => {
              setActiveCollectionId(null)
              setActiveDocument(null)
            }}
          >
            Study
          </h1>

          <DocPicker
            docs={docList.filter(isDocumentReady)}
            activeId={studyDocumentId}
            onSelect={(id) => {
              setActiveDocument(id)
              if (id) setActiveCollectionId(null)
            }}
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8 lg:p-12">
        {activeCollectionId ? (
          <CollectionStudyDashboard
            collectionId={activeCollectionId}
            onBack={() => setActiveCollectionId(null)}
            onStartStudy={handleStartFlashcard}
            onStartTeachback={(filters, resumeId) =>
              handleStartTeachback(filters, resumeId)
            }
            onNavigateToCollection={(id) => setActiveCollectionId(id)}
          />
        ) : studyDocumentId ? (
          <>
            {isFallingBack && (
              <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                The selected document is still ingesting. Showing your previous
                document while it finishes.
              </div>
            )}
            <FlashcardManager
              documentId={studyDocumentId}
              onStartStudy={handleStartFlashcard}
              onStartTeachback={(f) => handleStartTeachback(f)}
            />
          </>
        ) : (
          /* Landing page: goals + session manager + collection grid */
          <div className="flex flex-col gap-10">
            {/* (S211) Goals sub-section -- typed learning goals + progress */}
            <GoalsList />

            <SessionManager
              onContinueTeachback={(sessionId, documentId, collectionId) => {
                if (documentId) setActiveDocument(documentId)
                if (collectionId) setActiveCollectionId(collectionId)
                
                const filters: any = {}
                if (documentId) filters.document_id = documentId
                if (collectionId) filters.collection_id = collectionId
                
                handleStartTeachback(
                  Object.keys(filters).length > 0 ? filters : null,
                  sessionId
                )
              }}
            />

            {/* Focused Enclaves heading */}
            <div className="flex flex-col gap-2 max-w-2xl">
              <motion.h1
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="text-3xl font-bold tracking-tight text-foreground"
              >
                Focused Enclaves
              </motion.h1>
              <p className="text-muted-foreground text-lg">
                Grouped knowledge silos for topic-centric learning.
              </p>
            </div>

            {loadingCollections ? (
              <div className="flex py-20 justify-center">
                <Loader2 className="h-10 w-10 animate-spin text-primary" />
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {(() => {
                  const flatten = (items: any[], parentName: string | null = null): any[] => {
                    let result: any[] = []
                    items.forEach((item) => {
                      result.push({ ...item, _parentName: parentName, _isNested: parentName !== null })
                      if (item.children && item.children.length > 0) {
                        result = result.concat(flatten(item.children, item.name))
                      }
                    })
                    return result
                  }
                  const flatCollections = flatten(collections)
                  return flatCollections.map((coll, idx) => (
                    <motion.div
                      key={coll.id}
                      initial={{ opacity: 0, y: 15 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.05 }}
                      whileHover={{ y: -5 }}
                      onClick={() => {
                        setActiveCollectionId(coll.id)
                        setActiveDocument(null)
                      }}
                      className={`group relative cursor-pointer overflow-hidden rounded-3xl border p-6 shadow-sm transition-all hover:border-primary/40 hover:bg-card hover:shadow-xl ${
                        coll._isNested ? "border-primary/20 bg-card/30" : "border-border bg-card/40"
                      }`}
                    >
                      {coll._isNested && (
                        <div className="absolute top-3 right-3 flex items-center gap-1 text-[10px] text-muted-foreground/60">
                          <CornerDownRight size={10} />
                          <span className="font-medium">{coll._parentName}</span>
                        </div>
                      )}
                      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary transition-all group-hover:bg-primary group-hover:text-primary-foreground group-hover:scale-110">
                        <Layers size={24} />
                      </div>
                      <div className="mt-6 flex flex-col gap-2">
                        <h3 className="text-lg font-semibold text-foreground">{coll.name}</h3>
                        <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed opacity-70">
                          {coll.description || "Synthesize knowledge across documents and notes."}
                        </p>
                      </div>
                      <div className="mt-4 flex items-center gap-3">
                        {coll.document_count > 0 || coll.note_count > 0 ? (
                          <>
                            {coll.document_count > 0 && (
                              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                <BookOpen size={12} className="text-blue-500/70" />
                                {coll.document_count} {coll.document_count === 1 ? "doc" : "docs"}
                              </span>
                            )}
                            {coll.note_count > 0 && (
                              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                <StickyNote size={12} className="text-amber-500/70" />
                                {coll.note_count} {coll.note_count === 1 ? "note" : "notes"}
                              </span>
                            )}
                            {coll.children && coll.children.length > 0 && (
                              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                                <Layers size={12} className="text-primary/50" />
                                {coll.children.length} sub
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="text-[11px] text-muted-foreground/50 italic">No sources yet</span>
                        )}
                      </div>
                      <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-4">
                        <div className="text-xs font-semibold uppercase text-primary opacity-0 transition-opacity group-hover:opacity-100">
                          Enter Context
                        </div>
                        <ChevronRight size={16} className="text-primary translate-x-4 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
                      </div>
                    </motion.div>
                  ))
                })()}

                <motion.button
                  onClick={() => navigate("/notes")}
                  className="flex flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-border/60 bg-transparent p-6 transition-all hover:bg-accent/30 hover:border-primary/40 group text-muted-foreground"
                >
                  <Plus size={24} className="group-hover:scale-110 transition-transform" />
                  <div className="text-center">
                    <p className="text-sm font-semibold uppercase">New Enclave</p>
                  </div>
                </motion.button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

