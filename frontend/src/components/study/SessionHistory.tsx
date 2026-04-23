/**
 * SessionHistory -- scoped list of past study sessions (teach-back + flashcard)
 * for either a collection or a document. Inline delete + expandable teach-back
 * result details. Used by the collection dashboard and the per-document view.
 */

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Check,
  Clock,
  History,
  Loader2,
  MessageSquare,
  PlayCircle,
  Trash2,
  Zap,
} from "lucide-react"
import { toast } from "sonner"
import {
  type StudySessionItem,
  type TeachbackResultItem,
  deleteStudySession,
  fetchSessions,
  fetchSessionTeachbackResults,
  scoreBadgeClass,
} from "@/lib/studyApi"

type Scope =
  | { kind: "collection"; id: string }
  | { kind: "document"; id: string }

interface SessionHistoryProps {
  scope: Scope
  onResumeTeachback: (sessionId: string) => void
  title?: string
}

export function SessionHistory({
  scope,
  onResumeTeachback,
  title = "Session History",
}: SessionHistoryProps) {
  const queryClient = useQueryClient()
  const [modeFilter, setModeFilter] = useState<"teachback" | "flashcard" | "all">(
    "teachback",
  )
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)

  const queryKey = [
    "scoped-sessions",
    scope.kind,
    scope.id,
    modeFilter,
  ] as const

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      fetchSessions(1, 50, {
        collectionId: scope.kind === "collection" ? scope.id : undefined,
        documentId: scope.kind === "document" ? scope.id : undefined,
        mode: modeFilter === "all" ? undefined : modeFilter,
      }),
    staleTime: 5_000,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteStudySession,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["scoped-sessions", scope.kind, scope.id],
      })
      queryClient.invalidateQueries({ queryKey: ["study-sessions-active"] })
      queryClient.invalidateQueries({ queryKey: ["study-sessions-completed"] })
      setPendingDeleteId(null)
      toast.success("Session deleted")
    },
    onError: () => {
      toast.error("Failed to delete session")
      setPendingDeleteId(null)
    },
  })

  const sessions = data?.items ?? []
  const hasAny = sessions.length > 0

  const scopeLabel =
    scope.kind === "collection" ? "this enclave" : "this document"

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 font-semibold text-foreground">
          <History size={18} className="text-primary" />
          {title}
        </h3>
        <div className="flex items-center gap-1 rounded-lg bg-muted/50 p-1">
          {(["teachback", "flashcard", "all"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setModeFilter(m)}
              className={`rounded-md px-3 py-1 text-[11px] font-semibold uppercase tracking-wider transition-colors ${
                modeFilter === m
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {m === "teachback"
                ? "Teach-back"
                : m === "flashcard"
                  ? "Flashcards"
                  : "All"}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          Loading sessions...
        </div>
      ) : !hasAny ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-8 text-center">
          <History size={24} className="mx-auto mb-2 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            No{" "}
            {modeFilter === "all"
              ? "past"
              : modeFilter === "teachback"
                ? "teach-back"
                : "flashcard"}{" "}
            sessions yet for {scopeLabel}.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {sessions.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              isExpanded={expandedId === s.id}
              onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
              onResume={onResumeTeachback}
              confirmDelete={pendingDeleteId === s.id}
              onRequestDelete={() => setPendingDeleteId(s.id)}
              onCancelDelete={() => setPendingDeleteId(null)}
              onConfirmDelete={() => deleteMutation.mutate(s.id)}
              isDeleting={deleteMutation.isPending && pendingDeleteId === s.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface SessionRowProps {
  session: StudySessionItem
  isExpanded: boolean
  onToggle: () => void
  onResume: (sessionId: string) => void
  confirmDelete: boolean
  onRequestDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
  isDeleting: boolean
}

function SessionRow({
  session,
  isExpanded,
  onToggle,
  onResume,
  confirmDelete,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  isDeleting,
}: SessionRowProps) {
  const isTeachback = session.mode === "teachback"
  const isComplete = session.ended_at !== null

  const { data: teachbackResults, isLoading: tbLoading } = useQuery<
    TeachbackResultItem[]
  >({
    queryKey: ["session-teachback-results", session.id],
    queryFn: () => fetchSessionTeachbackResults(session.id),
    enabled: isExpanded && isTeachback,
  })

  const startedLabel = new Date(session.started_at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })

  const duration = session.duration_minutes
  const durationLabel =
    duration === null
      ? "In progress"
      : duration < 1
        ? "< 1 min"
        : `${Math.round(duration)} min`

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div
        className="flex cursor-pointer items-center gap-4 px-4 py-3 transition-colors hover:bg-accent/30"
        onClick={onToggle}
      >
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
            isTeachback
              ? "bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400"
              : "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
          }`}
        >
          {isTeachback ? <MessageSquare size={14} /> : <Zap size={14} />}
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-medium text-foreground">
            {isTeachback ? "Teach-back" : "Flashcard"} session
            {!isComplete && (
              <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                In progress
              </span>
            )}
          </span>
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock size={10} />
            {startedLabel}
            {session.collection_name && (
              <span className="truncate text-primary/70">
                -- {session.collection_name}
              </span>
            )}
            {!session.collection_name && session.document_title && (
              <span className="truncate text-primary/70">
                -- {session.document_title}
              </span>
            )}
          </span>
        </div>

        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Check size={12} className="text-green-500" />
            {session.cards_reviewed}
          </span>
          <span>{durationLabel}</span>
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
          {isTeachback && !isComplete && (
            <button
              onClick={() => onResume(session.id)}
              className="flex items-center gap-1 rounded-md bg-violet-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-violet-700"
              title="Continue this teach-back session"
            >
              <PlayCircle size={11} />
              Continue
            </button>
          )}
          {!confirmDelete ? (
            <button
              onClick={onRequestDelete}
              className="rounded p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
              title="Delete session"
            >
              <Trash2 size={13} />
            </button>
          ) : (
            <div className="flex items-center gap-1 text-xs">
              <span className="text-red-600">Delete?</span>
              <button
                onClick={onConfirmDelete}
                disabled={isDeleting}
                className="rounded bg-red-600 px-2 py-0.5 text-white hover:bg-red-700 disabled:opacity-50"
              >
                Yes
              </button>
              <button
                onClick={onCancelDelete}
                className="rounded border border-border px-2 py-0.5 hover:bg-accent"
              >
                No
              </button>
            </div>
          )}
        </div>
      </div>

      {isExpanded && isTeachback && (
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
                <div
                  key={r.id}
                  className="flex items-start justify-between gap-3 rounded-lg border border-border bg-card p-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">
                      {r.question}
                    </p>
                    {r.user_explanation && (
                      <blockquote className="mt-1 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                        {r.user_explanation}
                      </blockquote>
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
                  </div>
                  {r.score != null && (
                    <span
                      className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-bold ${scoreBadgeClass(r.score)}`}
                    >
                      {r.score}/100
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
