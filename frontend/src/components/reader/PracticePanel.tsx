/**
 * PracticePanel -- the Practice face of the reader's docked panel.
 *
 * It opens on the deck that exists for what you are reading, not on a
 * generator: the learner's question here is "what do I know about this", and
 * a count field with a Generate button answers a different one. Generating is
 * the way to fill an empty deck, so it sits below the run, not above it.
 *
 * A run's mode is fixed when it starts because POST /study/teachback/async
 * rewrites its session's mode -- offering both inside one run would silently
 * relabel it in the learner's session history.
 */

import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Brain, Loader2, MessageSquareQuote, X } from "lucide-react"

import { apiGet } from "@/lib/apiClient"
import type { Flashcard } from "@/lib/studyApi"
import {
  type PreparedStudySessionOutcome,
  type StudyMode,
  prepareSectionStudyFromCards,
  prepareStudySession,
} from "@/lib/studySessionService"

import { CardGenerator } from "./CardGenerator"
import { summariseDeck } from "./practiceDeck"
import { RecallRunner } from "./RecallRunner"

// A reading-session run, not a daily queue: the Study page's 50 is the number
// for clearing a backlog, and 50 cards is longer than the reading it interrupts.
const READER_CARD_LIMIT = 20

interface PracticePanelProps {
  documentId: string
  /** Set when a selection or a section scoped this face. */
  sectionId: string | undefined
  sectionHeading: string | undefined
  /** The selected passage, when one scoped this. Generation only. */
  context: string
  onClearScope: () => void
  /** Put the document on the passage a card came from. */
  onJumpToSource: (sectionId: string) => void
}

interface ActiveRun {
  mode: StudyMode
  initial: Exclude<PreparedStudySessionOutcome, { kind: "empty" }>
  scopeForBeginNew: Parameters<typeof prepareStudySession>[0]
}

export function PracticePanel({
  documentId,
  sectionId,
  sectionHeading,
  context,
  onClearScope,
  onJumpToSource,
}: PracticePanelProps) {
  const qc = useQueryClient()
  const [run, setRun] = useState<ActiveRun | null>(null)
  const [starting, setStarting] = useState<StudyMode | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const [generatedNote, setGeneratedNote] = useState<string | null>(null)

  const scoped = Boolean(context || sectionHeading)

  const deckKey = ["reader-deck", documentId, sectionId ?? null] as const
  const { data: deck, isLoading, isError, refetch } = useQuery<Flashcard[]>({
    queryKey: deckKey,
    queryFn: () =>
      apiGet<Flashcard[]>(
        `/flashcards/${documentId}`,
        sectionId ? { section_id: sectionId } : undefined,
      ),
  })

  const { total: deckTotal, due: dueCards } = summariseDeck(deck ?? [])

  async function start(mode: StudyMode, ahead: boolean) {
    setStarting(mode)
    setStartError(null)
    try {
      // Section scope always runs from an explicit card set: prepareStudySession
      // resolves an open session by document, so a section run would adopt the
      // document's and study the wrong cards.
      // useStudySession wants a scope for its Start-New path. The panel offers
      // no such button, and a section run must not be rebuilt from this: it
      // would resolve the document's open session and study the wrong cards.
      const scopeForBeginNew = {
        mode,
        documentId,
        cardLimit: READER_CARD_LIMIT,
        ...(sectionId ? { filters: { section_id: sectionId } } : {}),
      }
      const outcome =
        ahead || sectionId
          ? await prepareSectionStudyFromCards(
              documentId,
              (ahead ? (deck ?? []) : dueCards).slice(0, READER_CARD_LIMIT),
              mode,
            )
          : await prepareStudySession(scopeForBeginNew)
      if (outcome.kind === "empty") {
        setStartError("Nothing to run here yet. Generate a few cards first.")
        return
      }
      setRun({ mode, initial: outcome, scopeForBeginNew })
    } catch {
      setStartError("Could not start the run. Is the backend reachable?")
    } finally {
      setStarting(null)
    }
  }

  function endRun() {
    setRun(null)
    void qc.invalidateQueries({ queryKey: ["reader-deck", documentId] })
    void qc.invalidateQueries({ queryKey: ["section-heatmap", documentId] })
  }

  const scopeLabel = context
    ? `Selected text (${context.length} chars)`
    : sectionHeading
      ? `Section: ${sectionHeading}`
      : "This document"

  return (
    <div data-testid="docked-practice" className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">
            {run ? "Testing yourself on" : "Practice from"}
          </p>
          <p data-testid="practice-scope" className="line-clamp-2 text-sm font-medium text-foreground">
            {scopeLabel}
          </p>
        </div>
        {scoped && !run && (
          <button
            onClick={() => { setStartError(null); setGeneratedNote(null); onClearScope() }}
            aria-label="Clear the selected scope"
            title="Use the whole document"
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {run ? (
        <RecallRunner
          // A new run is a new mount, so the previous run's per-card state
          // cannot leak into it.
          key={run.initial.session.id}
          initial={run.initial}
          scopeForBeginNew={run.scopeForBeginNew}
          mode={run.mode}
          onJumpToSource={onJumpToSource}
          onDone={endRun}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin" />
              Looking at what you have here...
            </div>
          ) : isError ? (
            <div className="rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              Could not load this deck.
              <button onClick={() => void refetch()} className="ml-2 underline hover:no-underline">
                Retry
              </button>
            </div>
          ) : (
            <DeckState
              total={deckTotal}
              due={dueCards.length}
              starting={starting}
              onStart={start}
            />
          )}

          {startError && (
            <p className="mt-3 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {startError}
            </p>
          )}

          <div className="mt-5 border-t border-border pt-4">
            <CardGenerator
              documentId={documentId}
              sectionHeading={sectionHeading}
              context={context}
              onGenerated={(count) => {
                setGeneratedNote(
                  count === 0
                    ? "No cards came back. The passage may be too short to make any from."
                    : `${count} card${count === 1 ? "" : "s"} added. They are due now.`,
                )
                void qc.invalidateQueries({ queryKey: ["reader-deck", documentId] })
              }}
            />
            {generatedNote && (
              <p className="mt-2 text-xs text-muted-foreground">{generatedNote}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function DeckState({
  total,
  due,
  starting,
  onStart,
}: {
  total: number
  due: number
  starting: StudyMode | null
  onStart: (mode: StudyMode, ahead: boolean) => void
}) {
  if (total === 0) {
    return (
      <div>
        <p data-testid="deck-summary" className="text-sm text-foreground">
          Nothing to practise here yet.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Make a few cards from what you are reading and you can test yourself on them straight
          away.
        </p>
      </div>
    )
  }

  const ahead = due === 0
  return (
    <div>
      <p data-testid="deck-summary" className="text-sm font-medium text-foreground">
        {ahead
          ? `${total} card${total === 1 ? "" : "s"} here, none due right now.`
          : `${due} due now, of ${total} card${total === 1 ? "" : "s"} here.`}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {ahead
          ? "They are scheduled further out, which is the point of the schedule. Run them anyway if you want to know where you stand."
          : "The answer stays hidden until you have committed to one."}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <StartButton
          testId="start-recall"
          icon={Brain}
          label="Recall"
          hint="Guess, then check"
          busy={starting === "flashcard"}
          disabled={starting !== null}
          onClick={() => onStart("flashcard", ahead)}
        />
        <StartButton
          testId="start-explain"
          icon={MessageSquareQuote}
          label="Explain it"
          hint="Write, then get scored"
          busy={starting === "teachback"}
          disabled={starting !== null}
          onClick={() => onStart("teachback", ahead)}
        />
      </div>
    </div>
  )
}

function StartButton({
  testId,
  icon: Icon,
  label,
  hint,
  busy,
  disabled,
  onClick,
}: {
  testId: string
  icon: typeof Brain
  label: string
  hint: string
  busy: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      className="flex flex-col items-start gap-0.5 rounded-md border border-border bg-background px-3 py-2 text-left hover:border-primary hover:bg-muted/50 disabled:opacity-50"
    >
      <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Icon size={13} />}
        {label}
      </span>
      <span className="text-[11px] text-muted-foreground">{hint}</span>
    </button>
  )
}
