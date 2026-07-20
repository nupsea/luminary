// Final-screen layout for a completed teach-back session: aggregate stats
// + per-card results list + start-new / back-to-study buttons.

import { MessageSquare } from "lucide-react"
import { useEffect } from "react"

import { isButtonActivation, isTypingTarget } from "@/lib/keyboard"
import { type PendingTeachback } from "@/lib/studyApi"

import { TeachbackResultsPanel } from "./TeachbackResultsPanel"
import { useTeachbackPolling } from "./useTeachbackPolling"

interface SessionCompleteProps {
  reviewed: number
  onBack: () => void
  onStartNext: () => void
  pendingTeachbacks: PendingTeachback[]
  subjectLabel?: string | null
}

export function SessionComplete({
  reviewed,
  onBack,
  onStartNext,
  pendingTeachbacks,
  subjectLabel,
}: SessionCompleteProps) {
  const { results, stats } = useTeachbackPolling(pendingTeachbacks)

  const displayReviewed = stats.completedCount || reviewed

  // Enter activates the primary action; arrows/Esc are handled by the
  // session-level listener in TeachbackSession.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return
      if (isButtonActivation(e)) return
      if (e.key === "Enter") {
        e.preventDefault()
        if (stats.allDone) onStartNext()
        else onBack()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [stats.allDone, onStartNext, onBack])

  return (
    <div className="flex flex-col items-center gap-6 px-4 py-6">
      {stats.allDone ? (
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-violet-100 dark:bg-violet-900/30">
            <MessageSquare size={28} className="text-violet-600 dark:text-violet-400" />
          </div>
          <h2 className="text-2xl font-bold text-foreground">Session Complete</h2>
          {subjectLabel && (
            <p className="text-sm text-muted-foreground">
              Teach-back on{" "}
              <span className="font-medium text-foreground">{subjectLabel}</span>
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-1">
          <h2 className="text-2xl font-bold text-foreground">
            Evaluating Your Answers...
          </h2>
          {subjectLabel && (
            <p className="text-sm text-muted-foreground">
              Teach-back on{" "}
              <span className="font-medium text-foreground">{subjectLabel}</span>
            </p>
          )}
        </div>
      )}

      {stats.completedCount > 0 && (
        <div className="flex gap-8 text-center">
          <div className="flex flex-col items-center">
            <span className="text-3xl font-bold text-foreground">{displayReviewed}</span>
            <span className="text-sm text-muted-foreground">Cards explained</span>
          </div>
          <div className="flex flex-col items-center">
            <span
              className={`text-3xl font-bold ${
                stats.avgScore >= 80
                  ? "text-green-600"
                  : stats.avgScore >= 60
                    ? "text-amber-600"
                    : "text-red-600"
              }`}
            >
              {stats.avgScore}/100
            </span>
            <span className="text-sm text-muted-foreground">Average Score</span>
          </div>
          <div className="flex flex-col items-center">
            <span className="text-xl font-semibold text-muted-foreground">
              {stats.passCount}/{stats.completedCount}
            </span>
            <span className="text-sm text-muted-foreground">Passed</span>
          </div>
        </div>
      )}

      <TeachbackResultsPanel pending={pendingTeachbacks} stats={stats} results={results} />

      <div className="flex items-center gap-3">
        {stats.allDone && (
          <button
            onClick={onStartNext}
            data-kbnav
            className="rounded-lg bg-violet-600 px-6 py-2 text-sm font-medium text-white hover:bg-violet-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Start New Session
          </button>
        )}
        <button
          onClick={onBack}
          data-kbnav
          className={`rounded-lg px-6 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ${
            stats.allDone
              ? "border border-border text-muted-foreground hover:bg-accent"
              : "bg-violet-600 text-white hover:bg-violet-700"
          }`}
        >
          Back to Study
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {stats.allDone
          ? "← → to choose · Enter to confirm · Esc to go back"
          : "Enter or Esc to go back"}
      </p>
    </div>
  )
}
