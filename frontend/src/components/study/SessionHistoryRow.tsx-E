/**
 * SessionHistoryRow -- single row in any list of study sessions (teach-back).
 *
 * Consolidates what used to be two drift-prone copies (CompletedSessionRow in
 * SessionManager.tsx and SessionRow in SessionHistory.tsx). The expanded body
 * always uses the flippable TeachbackResultCard so the expected-answer toggle
 * is consistent across the app.
 */

import { useQuery } from "@tanstack/react-query"
import {
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
  MessageSquare,
  PlayCircle,
  RotateCw,
  Trash2,
} from "lucide-react"
import { useState } from "react"
import {
  type StudySessionItem,
  type TeachbackResultItem,
  fetchSessionTeachbackResults,
  scoreBadgeClass,
} from "@/lib/studyApi"

export function sessionLabel(session: StudySessionItem): string {
  return session.collection_name || session.document_title || "Untitled session"
}

function formatStarted(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatDuration(mins: number | null): string {
  if (mins === null) return "In progress"
  if (mins < 1) return "< 1 min"
  return `${Math.round(mins)} min`
}

interface SessionHistoryRowProps {
  session: StudySessionItem
  isExpanded: boolean
  onToggle: () => void
  isSelected: boolean
  onToggleSelect: () => void
  onDelete: (sessionId: string) => void
  isDeleting: boolean
  /** If provided and session is incomplete, show a Continue button. */
  onResume?: (sessionId: string) => void
  /** Show a chevron in the actions area. Defaults to true. */
  showChevron?: boolean
}

export function SessionHistoryRow({
  session,
  isExpanded,
  onToggle,
  isSelected,
  onToggleSelect,
  onDelete,
  isDeleting,
  onResume,
  showChevron = true,
}: SessionHistoryRowProps) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const isComplete = session.ended_at !== null
  const label = sessionLabel(session)

  const { data: teachbackResults, isLoading: tbLoading } = useQuery<
    TeachbackResultItem[]
  >({
    queryKey: ["session-teachback-results", session.id],
    queryFn: () => fetchSessionTeachbackResults(session.id),
    enabled: isExpanded,
    // Keep the expanded view live while evaluations land. Polls at 2s,
    // stops when no rows are pending.
    refetchInterval: (query) => {
      if (!isExpanded) return false
      const items = query.state.data
      if (!items) return session.has_pending_evaluations ? 2_000 : false
      return items.some((r) => r.status === "pending") ? 2_000 : false
    },
  })

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div
        className="flex cursor-pointer items-center gap-4 px-4 py-3 transition-colors hover:bg-accent/30"
        onClick={onToggle}
      >
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggleSelect}
          onClick={(e) => e.stopPropagation()}
          className="h-4 w-4 shrink-0 cursor-pointer accent-violet-600"
          title="Select for bulk action"
        />

        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400">
          <MessageSquare size={14} />
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium text-foreground">
            {label}
            {!isComplete && (
              <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                In progress
              </span>
            )}
            {isComplete && session.has_pending_evaluations && (
              <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-bold uppercase text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
                <Loader2 size={10} className="animate-spin" />
                Evaluating
              </span>
            )}
          </span>
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock size={10} />
            Teach-back -- {formatStarted(session.started_at)}
          </span>
        </div>

        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Check size={12} className="text-green-500" />
            {session.cards_reviewed}
          </span>
          <span>{formatDuration(session.duration_minutes)}</span>
          {session.accuracy_pct != null && (
            <span
              className={`rounded-full px-2 py-0.5 font-bold ${
                session.accuracy_pct >= 80
                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                  : session.accuracy_pct >= 60
                    ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                    : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
              }`}
            >
              {session.accuracy_pct}%
            </span>
          )}
        </div>

        <div
          className="flex items-center gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          {onResume && (
            <button
              onClick={() => onResume(session.id)}
              className="flex items-center gap-1 rounded-md bg-violet-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-violet-700"
              title={
                isComplete
                  ? "Reopen this teach-back session to add more answers"
                  : "Continue this teach-back session"
              }
            >
              <PlayCircle size={11} />
              {isComplete ? "Resume" : "Continue"}
            </button>
          )}
          {!confirmDelete ? (
            <button
              onClick={() => setConfirmDelete(true)}
              className="rounded p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
              title="Delete session"
            >
              <Trash2 size={13} />
            </button>
          ) : (
            <div className="flex items-center gap-1 text-xs">
              <span className="text-red-600">Delete?</span>
              <button
                onClick={() => {
                  onDelete(session.id)
                  setConfirmDelete(false)
                }}
                disabled={isDeleting}
                className="rounded bg-red-600 px-2 py-0.5 text-white hover:bg-red-700 disabled:opacity-50"
              >
                Yes
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="rounded border border-border px-2 py-0.5 hover:bg-accent"
              >
                No
              </button>
            </div>
          )}
          {showChevron &&
            (isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
        </div>
      </div>

      {isExpanded && (
        <div className="border-t border-border bg-muted/20 px-4 py-3">
          {tbLoading ? (
            <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
              <Loader2 size={12} className="animate-spin" />
              Loading results...
            </div>
          ) : !teachbackResults || teachbackResults.length === 0 ? (
            <p className="py-1 text-sm text-muted-foreground">
              No results recorded.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              {teachbackResults.map((r) => (
                <TeachbackResultCard key={r.id} result={r} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface TeachbackResultCardProps {
  result: TeachbackResultItem
}

function TeachbackResultCard({ result: r }: TeachbackResultCardProps) {
  const [showAnswer, setShowAnswer] = useState(false)
  const hasExpected = Boolean(r.expected_answer && r.expected_answer.trim())

  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-border bg-card p-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{r.question}</p>

        {!showAnswer ? (
          <>
            {r.user_explanation && (
              <blockquote className="mt-1 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                {r.user_explanation}
              </blockquote>
            )}
            {r.rubric && (
              <div className="mt-2 flex flex-col gap-1 text-[11px] text-muted-foreground">
                <div className="rounded-md bg-muted/30 p-2">
                  <span className="font-semibold text-foreground">Clarity: </span>
                  {r.rubric.clarity.evidence}
                </div>
              </div>
            )}
            {r.missing_points && r.missing_points.length > 0 && (
              <div className="mt-2 text-[11px] text-muted-foreground">
                <span className="font-semibold">Missing: </span>
                {r.missing_points.join("; ")}
              </div>
            )}
            {r.misconceptions && r.misconceptions.length > 0 && (
              <div className="mt-1 text-[11px] text-red-600 dark:text-red-400">
                <span className="font-semibold">Misconceptions: </span>
                {r.misconceptions.join("; ")}
              </div>
            )}
          </>
        ) : (
          <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 p-2 dark:border-emerald-900/40 dark:bg-emerald-950/20">
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
              Expected answer
            </div>
            <p className="whitespace-pre-wrap text-xs text-foreground">
              {hasExpected
                ? r.expected_answer
                : "No reference answer available for this card."}
            </p>
          </div>
        )}
      </div>

      <div className="flex shrink-0 flex-col items-end gap-2">
        {r.score != null && (
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${scoreBadgeClass(r.score)}`}
          >
            {r.score}/100
          </span>
        )}
        <button
          type="button"
          onClick={() => setShowAnswer((v) => !v)}
          className="flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] font-semibold text-muted-foreground hover:bg-accent hover:text-foreground"
          title={showAnswer ? "Show evaluation" : "Show expected answer"}
        >
          <RotateCw size={11} />
          {showAnswer ? "Evaluation" : "Answer"}
        </button>
      </div>
    </div>
  )
}
