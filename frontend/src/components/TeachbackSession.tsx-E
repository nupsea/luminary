/**
 * TeachbackSession -- dedicated teach-back study experience.
 *
 * Separated from FlashcardSession to provide:
 *  - Persistent sessions that survive tab switches
 *  - Resume incomplete sessions
 *  - Rich feedback per card with retry
 *  - Session summary with all results
 *
 * Sub-components live in components/Teachback/.
 */

import { AnimatePresence, motion } from "framer-motion"
import { useQuery } from "@tanstack/react-query"
import { Loader2, MessageSquare } from "lucide-react"
import { useState } from "react"

import { ProgressBar } from "@/components/Teachback/ProgressBar"
import { SessionComplete } from "@/components/Teachback/SessionComplete"
import { TeachbackPanel } from "@/components/Teachback/TeachbackPanel"
import {
  useStudySession,
  type UseStudySessionInput,
} from "@/hooks/useStudySession"
import {
  type PendingTeachback,
  fetchTeachbackResults,
  submitTeachbackAsync,
} from "@/lib/studyApi"

interface TeachbackSessionProps {
  initial: UseStudySessionInput["initial"]
  scopeForBeginNew: UseStudySessionInput["scopeForBeginNew"]
  onExit: () => void
  subjectLabel?: string | null
}

// Teach-back is deliberate and slow; capping the queue keeps sessions focused
// and prevents a surprise 50-question marathon when many cards are due.
export const TEACHBACK_CARD_LIMIT = 10

export function TeachbackSession({
  initial,
  scopeForBeginNew,
  onExit,
  subjectLabel,
}: TeachbackSessionProps) {
  const [pendingTeachbacks, setPendingTeachbacks] = useState<PendingTeachback[]>([])

  const {
    sessionState,
    sessionId,
    queue,
    currentIndex,
    reviewed,
    total,
    setCurrentIndex,
    setReviewed,
    completeSession,
    exit,
    beginNew,
  } = useStudySession({
    initial,
    scopeForBeginNew,
    onResumeLoaded: (prev) => {
      setPendingTeachbacks(
        prev.map((r) => ({
          id: r.id,
          flashcardId: r.flashcard_id,
          question: r.question,
        })),
      )
    },
  })

  // Poll for live results during active session
  const realTeachbackIds = pendingTeachbacks
    .map((t) => t.id)
    .filter((id) => !id.startsWith("temp-") && !id.startsWith("error-"))
  const { data: liveResults } = useQuery({
    queryKey: ["teachback-live-poll", ...realTeachbackIds],
    queryFn: () => fetchTeachbackResults(realTeachbackIds),
    refetchInterval: (query) => {
      if (sessionState !== "studying") return false
      const items = query.state.data
      if (!items) return 2000
      return items.some((r) => r.status === "pending") ? 2000 : false
    },
    enabled: sessionState === "studying" && realTeachbackIds.length > 0,
  })

  function handleTeachbackSubmit(cardId: string, question: string, explanation: string) {
    const tempId = `temp-${Date.now()}-${cardId}`
    setPendingTeachbacks((prev) => [...prev, { id: tempId, flashcardId: cardId, question }])
    void submitTeachbackAsync(cardId, explanation, sessionId)
      .then(({ id }) => {
        setPendingTeachbacks((prev) => prev.map((t) => (t.id === tempId ? { ...t, id } : t)))
      })
      .catch((err) => {
        console.warn("Teachback async submit failed", err)
        setPendingTeachbacks((prev) =>
          prev.map((t) => (t.id === tempId ? { ...t, id: `error-${tempId}` } : t)),
        )
      })
  }

  function handleTeachbackNext() {
    const nextIndex = currentIndex + 1
    setReviewed((r) => r + 1)
    if (nextIndex >= queue.length) {
      void completeSession()
    } else {
      setCurrentIndex(nextIndex)
    }
  }

  async function handleBackToStudy() {
    await exit(onExit)
  }

  if (sessionState === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={32} className="animate-spin text-violet-500" />
      </div>
    )
  }

  if (sessionState === "empty") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
        <MessageSquare size={40} className="text-muted-foreground/40" />
        {subjectLabel && (
          <p className="text-xs uppercase tracking-wider text-muted-foreground/70">
            {subjectLabel}
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          No cards due for teach-back right now.
        </p>
        <button
          onClick={onExit}
          className="rounded-lg border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-accent"
        >
          Back to Study
        </button>
      </div>
    )
  }

  if (sessionState === "complete") {
    return (
      <div className="flex h-full items-start justify-center overflow-auto py-8">
        <SessionComplete
          reviewed={reviewed}
          subjectLabel={subjectLabel}
          onBack={() => void exit(onExit)}
          onStartNext={() => {
            setPendingTeachbacks([])
            void beginNew()
          }}
          pendingTeachbacks={pendingTeachbacks}
        />
      </div>
    )
  }

  const currentCard = queue[currentIndex]
  if (!currentCard) return null

  // Derive teach-back evaluation state for current card
  const currentCardTeachbacks = pendingTeachbacks.filter((t) => t.flashcardId === currentCard.id)
  const latestTeachbackEntry = currentCardTeachbacks[currentCardTeachbacks.length - 1] ?? null
  const latestTeachbackId = latestTeachbackEntry?.id ?? null
  const isLatestTemp = latestTeachbackId?.startsWith("temp-") ?? false
  const isLatestError = latestTeachbackId?.startsWith("error-") ?? false
  const currentLiveResult =
    latestTeachbackId && !isLatestTemp && !isLatestError
      ? (liveResults?.find((r) => r.id === latestTeachbackId && r.status !== "pending") ?? null)
      : null
  const isTeachbackEvaluating = latestTeachbackEntry != null && currentLiveResult == null && !isLatestError
  const previousAttemptResult =
    liveResults
      ?.filter(
        (r) =>
          r.flashcard_id === currentCard.id &&
          r.status === "complete" &&
          r.id !== latestTeachbackId,
      )
      .slice(-1)[0] ?? null

  return (
    <div className="flex h-full flex-col items-center gap-6 overflow-auto bg-background px-6 py-8">
      {/* Header */}
      <div className="flex w-full max-w-2xl flex-col gap-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare size={18} className="text-violet-500" />
            <span className="text-sm font-semibold text-violet-600 dark:text-violet-400">
              Teach-back Session
            </span>
          </div>
          <span className="rounded-full bg-violet-100 px-3 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
            Card {currentIndex + 1} of {queue.length}
          </span>
        </div>
        {subjectLabel && (
          <p className="text-xs text-muted-foreground">
            Subject:{" "}
            <span className="font-medium text-foreground">{subjectLabel}</span>
          </p>
        )}
      </div>

      <ProgressBar done={reviewed} total={total} />

      <AnimatePresence mode="wait">
        <motion.div
          key={`${currentCard.id}-${currentIndex}`}
          initial={{ x: 200, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -200, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="w-full max-w-2xl"
        >
          <TeachbackPanel
            card={currentCard}
            onNext={handleTeachbackNext}
            onSubmitAsync={handleTeachbackSubmit}
            currentResult={currentLiveResult}
            isEvaluating={isTeachbackEvaluating}
            previousAttempt={previousAttemptResult}
          />
        </motion.div>
      </AnimatePresence>

      <button
        onClick={() => void handleBackToStudy()}
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        End session
      </button>
    </div>
  )
}
