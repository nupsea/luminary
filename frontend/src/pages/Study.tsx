/**
 * Study tab — Flashcard section and Progress section placeholder
 *
 * Flashcard section:
 *  - Generate panel: count selector, scope (full/section), Generate button
 *  - Flashcard list: show/hide answer, inline edit, delete with confirmation
 *  - Bottom bar: card count, Start Studying, CSV export
 * Study session:
 *  - Full-screen StudySession replaces tab content when studying
 */

import { useQuery } from "@tanstack/react-query"
import { useState, useEffect } from "react"
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  ChevronRight,
  CornerDownRight,
  Layers,
  Loader2,
  Plus,
  StickyNote,
  Zap,
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import { useBackNavigation } from "@/hooks/useBackNavigation"
import { motion } from "framer-motion"
import { toast } from "sonner"
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
import type { Flashcard } from "@/lib/studyApi"
import {
  type PrepareStudySessionOptions,
  type PreparedStudySessionOutcome,
  type StudyMode,
  prepareSectionStudyFromCards,
  prepareStudySession,
} from "@/lib/studySessionService"


// Document list for the in-tab picker

import { apiGet, apiPost } from "@/lib/apiClient"

import type { DocListItem } from "./Study/types"
import { fetchDocList } from "./Study/api"
import { DocPicker } from "./Study/DocPicker"
import { DocumentTopics } from "@/components/DocumentTopics"
import { FlashcardManager } from "./Study/FlashcardManager"



export type { DocListItem } from "./Study/types"  // re-exported for Progress.tsx

// SessionHistoryTab replaced by SessionManager component

// DocPicker now lives in pages/Study/DocPicker.tsx.

const _SESSION_SIZE = 15

// Study landing's lead action: the due-review CTA. Surfacing today's recall load
// here (rather than only on the Hub) means opening Study always answers "what
// should I do now?" before the collection grid.
function StartReviewDueCard({ onStart }: { onStart: () => void }) {
  const { data } = useQuery<{ due_today: number }>({
    queryKey: ["study-due-count"],
    queryFn: () => apiGet<{ due_today: number }>("/study/due-count"),
    staleTime: 30_000,
  })
  const due = data?.due_today ?? 0
  const sessionSize = Math.min(_SESSION_SIZE, due)
  const estMin = Math.max(1, Math.round(sessionSize * 0.9))

  if (due === 0) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-border bg-card/50 px-5 py-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
          <Zap size={18} />
        </span>
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-foreground">You're all caught up</span>
          <span className="text-xs text-muted-foreground">
            No cards due right now. Pick a collection below to study ahead.
          </span>
        </div>
      </div>
    )
  }

  return (
    <button
      onClick={onStart}
      className="group flex items-center gap-4 rounded-2xl bg-gradient-to-br from-primary via-primary to-primary/75 px-6 py-5 text-left text-primary-foreground shadow-md shadow-primary/15 transition-all hover:shadow-lg hover:shadow-primary/20"
    >
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
        <Zap size={20} />
      </span>
      <div className="flex flex-1 flex-col gap-0.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-primary-foreground/80">
          Start your due review
        </span>
        <span className="text-lg font-semibold sm:text-xl">
          {due} card{due !== 1 ? "s" : ""} due
        </span>
        <span className="text-xs text-primary-foreground/75">
          {sessionSize}-card session · ~{estMin} min
        </span>
      </div>
      <ArrowRight size={20} className="shrink-0 text-primary-foreground/85 transition-transform group-hover:translate-x-0.5" />
    </button>
  )
}

export default function Study() {
  const navigate = useNavigate()
  const { canGoBack, backLabel, goBack } = useBackNavigation()
  const {
    setActiveDocument,
    activeCollectionId,
    setActiveCollectionId,
    pendingStudyResume,
    setPendingStudyResume,
    pendingStudyStart,
    setPendingStudyStart,
  } = useAppStore()

  // Effective doc: ready-only fallback so we never feed an in-progress doc
  // into prepareStudySession or FlashcardManager. Both depend on populated
  // chunks/embeddings/flashcards, which simply don't exist mid-ingestion.
  const { doc: effectiveDoc, effectiveDocumentId, isFallingBack, rawActiveId } =
    useEffectiveActiveDocument()
  // When a collection is active, suppress the lastReadyDocumentId fallback so
  // the DocPicker shows no selection and startStudy doesn't mix a stale document
  // scope into a collection-scoped session.
  const studyDocumentId = activeCollectionId ? null : effectiveDocumentId

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
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        return await apiGet<any[]>("/collections/tree")
      } catch {
        return []
      }
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

  const handleStartFlashcard = (filters?: StudyFiltersLike, resumeId?: string) => {
    void startStudy("flashcard", filters ?? null, resumeId ?? null)
  }

  const handleStartTeachback = (
    filters?: StudyFiltersLike,
    resumeId?: string,
  ) => {
    void startStudy("teachback", filters ?? null, resumeId ?? null)
  }

  // Study one coherent SECTION in either mode: use its existing cards (or generate them from its own
  // text), then run a flashcard review or teach-back scoped to that section. Reuses the existing
  // generator + StudySession/TeachbackSession + FSRS.
  const runSectionStudy = async (
    sectionId: string,
    sectionHeading: string,
    mode: StudyMode,
  ) => {
    if (studyPhase.phase !== "idle" || !studyDocumentId) return
    setStudyPhase({ phase: "preparing", mode })
    try {
      const existing = await apiGet<{ items: Flashcard[] }>("/flashcards/search", {
        document_id: studyDocumentId,
        section_id: sectionId,
        page_size: FLASHCARD_CARD_LIMIT,
      })
      let cards = existing.items ?? []
      if (cards.length === 0) {
        cards = await apiPost<Flashcard[]>("/flashcards/generate", {
          document_id: studyDocumentId,
          scope: "section",
          section_heading: sectionHeading,
          count: 8,
        })
      }
      if (!cards || cards.length === 0) {
        setStudyPhase({ phase: "idle" })
        toast.error("Couldn't generate cards for this section — is the model (Ollama) running?")
        return
      }
      const outcome = await prepareSectionStudyFromCards(studyDocumentId, cards, mode)
      const scope: PrepareStudySessionOptions = {
        mode,
        documentId: studyDocumentId,
        collectionId: null,
        filters: { section_id: sectionId },
        cardLimit: FLASHCARD_CARD_LIMIT,
        resumeSessionId: null,
      }
      setStudyPhase({ phase: "ready", mode, outcome, scopeForBeginNew: scope })
    } catch (err) {
      console.warn("Failed to study section", err)
      setStudyPhase({ phase: "idle" })
      toast.error("Couldn't start studying this section.")
    }
  }

  const handleStudySection = (sectionId: string, sectionHeading: string) =>
    void runSectionStudy(sectionId, sectionHeading, "flashcard")
  const handleTeachbackSection = (sectionId: string, sectionHeading: string) =>
    void runSectionStudy(sectionId, sectionHeading, "teachback")

  // Auto-resume a session interrupted by "Open in reader" navigation.
  // SourceContextPanel saves session info to the store before navigating away;
  // when the user clicks "Back to Study" we land here in idle state and resume.
  useEffect(() => {
    if (pendingStudyResume && studyPhase.phase === "idle") {
      const { sessionId, mode } = pendingStudyResume
      setPendingStudyResume(null)
      void startStudy(mode, null, sessionId)
    }
  // startStudy is re-created each render; only trigger when pendingStudyResume changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingStudyResume])

  // Auto-start a fresh session when arriving from a direct "Study this document"
  // action (the reader header). Waits until the intended document scope has
  // resolved so we never fall back to an unscoped daily review.
  useEffect(() => {
    if (!pendingStudyStart || studyPhase.phase !== "idle") return
    if (pendingStudyStart.documentId && studyDocumentId !== pendingStudyStart.documentId) return
    const { mode } = pendingStudyStart
    setPendingStudyStart(null)
    void startStudy(mode, null, null)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingStudyStart, studyDocumentId])

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
          {canGoBack && (
            <button
              onClick={goBack}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <ArrowLeft size={12} />
              {backLabel}
            </button>
          )}
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
            {isFallingBack && (() => {
              const ingestingTitle = docList.find(d => d.id === rawActiveId)?.title ?? "A recently selected document"
              const fallbackTitle = effectiveDoc?.title ?? "this document"
              return (
                <div className="mb-4 flex items-center justify-between gap-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  <span>
                    <span className="font-medium">{ingestingTitle}</span> is still processing.
                    {" "}Showing <span className="font-medium">{fallbackTitle}</span> in the meantime.
                  </span>
                  <button
                    onClick={() => setActiveDocument(null)}
                    className="shrink-0 text-xs underline underline-offset-2 hover:text-amber-900"
                  >
                    Clear selection
                  </button>
                </div>
              )
            })()}
            <DocumentTopics
              documentId={studyDocumentId}
              onStudySection={handleStudySection}
              onTeachbackSection={handleTeachbackSection}
            />
            <FlashcardManager
              documentId={studyDocumentId}
              onStartStudy={handleStartFlashcard}
              onStartTeachback={(f) => handleStartTeachback(f)}
            />
          </>
        ) : (
          /* Landing page: due-review CTA + session manager + collection grid.
             Goals now live solely on Progress to remove the Study/Progress overlap. */
          <div className="flex flex-col gap-10">
            <StartReviewDueCard onStart={() => handleStartFlashcard()} />

            <SessionManager
              onContinue={(sessionId, documentId, collectionId, mode) => {
                if (documentId) setActiveDocument(documentId)
                if (collectionId) setActiveCollectionId(collectionId)
                void startStudy(mode === "flashcard" ? "flashcard" : "teachback", null, sessionId)
              }}
            />

            {/* Collections heading */}
            <div className="flex flex-col gap-2 max-w-2xl">
              <motion.h1
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="text-3xl font-bold tracking-tight text-foreground"
              >
                Collections
              </motion.h1>
              <p className="text-muted-foreground text-lg">
                Group documents and notes by topic to study them together.
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
                          {coll.description || "Group documents and notes to study them together."}
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
                          Open
                        </div>
                        <ChevronRight size={16} className="text-primary translate-x-4 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" />
                      </div>
                    </motion.div>
                  ))
                })()}

                <motion.button
                  onClick={() => navigate("/notes", { state: { from: "/study" } })}
                  className="flex flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-border/60 bg-transparent p-6 transition-all hover:bg-accent/30 hover:border-primary/40 group text-muted-foreground"
                >
                  <Plus size={24} className="group-hover:scale-110 transition-transform" />
                  <div className="text-center">
                    <p className="text-sm font-semibold uppercase">New collection</p>
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

