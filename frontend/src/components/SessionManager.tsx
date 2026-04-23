/**
 * SessionManager -- view, continue, review, and delete persisted study sessions.
 *
 * Shows teach-back sessions prominently with "Continue" for incomplete ones.
 * Flashcard sessions are shown in a compact history list.
 */

import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  CalendarDays,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
  MessageSquare,
  PlayCircle,
  Trash2,
  Zap,
} from "lucide-react"
import { toast } from "sonner"
import {
  type StudySessionItem,
  type SessionListResponse,
  type TeachbackResultItem,
  fetchSessions,
  deleteStudySession,
  fetchSessionTeachbackResults,
  scoreBadgeClass,
} from "@/lib/studyApi"
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Session card detail types
// ---------------------------------------------------------------------------

interface SessionCardDetail {
  flashcard_id: string
  question: string
  rating: string
  is_correct: boolean
  reviewed_at: string
}

async function fetchSessionCards(sessionId: string): Promise<SessionCardDetail[]> {
  const res = await fetch(`${API_BASE}/study/sessions/${encodeURIComponent(sessionId)}/cards`)
  if (!res.ok) throw new Error("Failed to load session cards")
  return res.json() as Promise<SessionCardDetail[]>
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
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

// ---------------------------------------------------------------------------
// ActiveSessionCard -- for incomplete teach-back sessions
// ---------------------------------------------------------------------------

interface ActiveSessionCardProps {
  session: StudySessionItem
  onContinue: (sessionId: string) => void
  onDelete: (sessionId: string) => void
  isDeleting: boolean
}

function ActiveSessionCard({ session, onContinue, onDelete, isDeleting }: ActiveSessionCardProps) {
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-violet-200 bg-gradient-to-br from-violet-50/50 to-background p-5 shadow-sm transition-all hover:shadow-md dark:border-violet-800 dark:from-violet-950/20">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <MessageSquare size={16} className="text-violet-500" />
          <span className="text-xs font-semibold uppercase tracking-wider text-violet-600 dark:text-violet-400">
            Teach-back -- In Progress
          </span>
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock size={12} />
          {formatDate(session.started_at)}
        </div>
      </div>

      <div className="flex items-center gap-4">
        {session.cards_reviewed > 0 && (
          <div className="flex items-center gap-1.5 text-sm text-foreground">
            <Check size={14} className="text-green-500" />
            <span className="font-medium">{session.cards_reviewed}</span>
            <span className="text-muted-foreground">cards reviewed</span>
          </div>
        )}
        {session.document_title && (
          <span className="text-xs text-muted-foreground">{session.document_title}</span>
        )}
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={() => onContinue(session.id)}
          className="flex items-center gap-2 rounded-lg bg-violet-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-violet-700"
        >
          <PlayCircle size={16} />
          Continue Session
        </button>
        {!confirmDelete ? (
          <button
            onClick={() => setConfirmDelete(true)}
            className="rounded-lg p-2 text-muted-foreground hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
            title="Delete session"
          >
            <Trash2 size={14} />
          </button>
        ) : (
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-red-600">Delete this session?</span>
            <button
              onClick={() => onDelete(session.id)}
              disabled={isDeleting}
              className="rounded bg-red-600 px-2 py-0.5 text-white text-xs hover:bg-red-700 disabled:opacity-50"
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
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// CompletedSessionRow -- expandable row for completed sessions
// ---------------------------------------------------------------------------

interface CompletedSessionRowProps {
  session: StudySessionItem
  isExpanded: boolean
  onToggle: () => void
  onDelete: (sessionId: string) => void
  isDeleting: boolean
}

function CompletedSessionRow({
  session,
  isExpanded,
  onToggle,
  onDelete,
  isDeleting,
}: CompletedSessionRowProps) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const isTeachback = session.mode === "teachback"

  const { data: teachbackResults, isLoading: tbLoading } = useQuery<TeachbackResultItem[]>({
    queryKey: ["session-teachback-results", session.id],
    queryFn: () => fetchSessionTeachbackResults(session.id),
    enabled: isExpanded && isTeachback,
  })

  const { data: sessionCards, isLoading: cardsLoading } = useQuery<SessionCardDetail[]>({
    queryKey: ["session-cards", session.id],
    queryFn: () => fetchSessionCards(session.id),
    enabled: isExpanded && !isTeachback,
  })

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div
        className="flex items-center gap-4 px-4 py-3 cursor-pointer hover:bg-accent/30 transition-colors"
        onClick={onToggle}
      >
        {/* Mode icon */}
        <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
          isTeachback
            ? "bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400"
            : "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
        }`}>
          {isTeachback ? <MessageSquare size={14} /> : <Zap size={14} />}
        </div>

        {/* Date + mode */}
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-sm font-medium text-foreground">
            {isTeachback ? "Teach-back" : "Flashcard"} Session
          </span>
          <span className="text-xs text-muted-foreground">
            {formatDate(session.started_at)}
            {session.document_title && ` -- ${session.document_title}`}
          </span>
        </div>

        {/* Stats */}
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span>{session.cards_reviewed} cards</span>
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

        {/* Actions */}
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
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
                onClick={() => onDelete(session.id)}
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
          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </div>

      {/* Expanded detail */}
      {isExpanded && (
        <div className="border-t border-border bg-muted/20 px-4 py-3">
          {isTeachback ? (
            tbLoading ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                <Loader2 size={12} className="animate-spin" />
                Loading results...
              </div>
            ) : !teachbackResults || teachbackResults.length === 0 ? (
              <p className="text-sm text-muted-foreground py-1">No results recorded.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {teachbackResults.map((r) => (
                  <div key={r.id} className="flex items-start justify-between gap-3 rounded-lg border border-border bg-card p-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground">{r.question}</p>
                      {r.user_explanation && (
                        <blockquote className="mt-1 border-l-2 border-border pl-2 text-xs text-muted-foreground italic truncate">
                          {r.user_explanation}
                        </blockquote>
                      )}
                    </div>
                    <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-bold ${scoreBadgeClass(r.score ?? 0)}`}>
                      {r.score}/100
                    </span>
                  </div>
                ))}
              </div>
            )
          ) : (
            cardsLoading ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                <Loader2 size={12} className="animate-spin" />
                Loading cards...
              </div>
            ) : !sessionCards || sessionCards.length === 0 ? (
              <p className="text-sm text-muted-foreground py-1">No card events recorded.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pb-1 pr-4 font-medium">Question</th>
                    <th className="pb-1 pr-4 font-medium">Rating</th>
                    <th className="pb-1 font-medium">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {sessionCards.map((card) => (
                    <tr key={card.flashcard_id} className="border-t border-border/50">
                      <td className="py-1 pr-4 text-foreground">{card.question}</td>
                      <td className="py-1 pr-4 text-muted-foreground capitalize">{card.rating}</td>
                      <td className="py-1">
                        {card.is_correct ? (
                          <span className="text-green-600">Correct</span>
                        ) : (
                          <span className="text-red-500">Incorrect</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SessionManager -- main export
// ---------------------------------------------------------------------------

interface SessionManagerProps {
  onContinueTeachback: (sessionId: string) => void
}

export function SessionManager({ onContinueTeachback }: SessionManagerProps) {
  const [tab, setTab] = useState<"active" | "completed">("active")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [completedPage, setCompletedPage] = useState(1)
  const queryClient = useQueryClient()

  // Fetch incomplete sessions (teach-back only for "active" tab)
  const { data: activeSessions, isLoading: activeLoading } = useQuery({
    queryKey: ["study-sessions-active"],
    queryFn: () => fetchSessions(1, 20, { mode: "teachback", status: "incomplete" }),
    staleTime: 10_000,
  })

  // Fetch completed sessions (all modes)
  const { data: completedSessions, isLoading: completedLoading } = useQuery({
    queryKey: ["study-sessions-completed", completedPage],
    queryFn: () => fetchSessions(completedPage, 20, { status: "complete" }),
    enabled: tab === "completed",
  })

  const deleteMutation = useMutation({
    mutationFn: deleteStudySession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["study-sessions-active"] })
      queryClient.invalidateQueries({ queryKey: ["study-sessions-completed"] })
      toast.success("Session deleted")
    },
    onError: () => {
      toast.error("Failed to delete session")
    },
  })

  const activeItems = activeSessions?.items ?? []
  const completedItems = completedSessions?.items ?? []
  const completedTotal = completedSessions?.total ?? 0
  const completedTotalPages = Math.ceil(completedTotal / 20)

  return (
    <div className="flex flex-col gap-6">
      {/* Tab bar */}
      <div className="flex items-center gap-1 rounded-lg bg-muted/50 p-1 self-start">
        <button
          onClick={() => setTab("active")}
          className={`flex items-center gap-1.5 rounded-md px-4 py-1.5 text-xs font-semibold transition-colors ${
            tab === "active"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <PlayCircle size={13} />
          Active
          {activeItems.length > 0 && (
            <span className="ml-1 rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-bold text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
              {activeItems.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab("completed")}
          className={`flex items-center gap-1.5 rounded-md px-4 py-1.5 text-xs font-semibold transition-colors ${
            tab === "completed"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <CalendarDays size={13} />
          History
        </button>
      </div>

      {/* Active tab */}
      {tab === "active" && (
        <div className="flex flex-col gap-3">
          {activeLoading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              Loading active sessions...
            </div>
          ) : activeItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-8 text-center">
              <MessageSquare size={28} className="mx-auto mb-3 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">No active teach-back sessions.</p>
              <p className="mt-1 text-xs text-muted-foreground/70">
                Start a new teach-back session to practice explaining concepts in your own words.
              </p>
            </div>
          ) : (
            activeItems.map((sess) => (
              <ActiveSessionCard
                key={sess.id}
                session={sess}
                onContinue={onContinueTeachback}
                onDelete={(id) => deleteMutation.mutate(id)}
                isDeleting={deleteMutation.isPending}
              />
            ))
          )}
        </div>
      )}

      {/* Completed tab */}
      {tab === "completed" && (
        <div className="flex flex-col gap-3">
          {completedLoading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              Loading session history...
            </div>
          ) : completedItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-8 text-center">
              <CalendarDays size={28} className="mx-auto mb-3 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">
                No completed sessions yet. Finish a study session to see it here.
              </p>
            </div>
          ) : (
            <>
              {completedItems.map((sess) => (
                <CompletedSessionRow
                  key={sess.id}
                  session={sess}
                  isExpanded={expandedId === sess.id}
                  onToggle={() => setExpandedId(expandedId === sess.id ? null : sess.id)}
                  onDelete={(id) => deleteMutation.mutate(id)}
                  isDeleting={deleteMutation.isPending}
                />
              ))}

              {completedTotalPages > 1 && (
                <div className="flex items-center justify-between pt-2 text-sm text-muted-foreground">
                  <button
                    onClick={() => setCompletedPage((p) => Math.max(1, p - 1))}
                    disabled={completedPage === 1}
                    className="rounded border border-border px-3 py-1 hover:bg-accent disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <span>
                    Page {completedPage} of {completedTotalPages}
                  </span>
                  <button
                    onClick={() => setCompletedPage((p) => Math.min(completedTotalPages, p + 1))}
                    disabled={completedPage === completedTotalPages}
                    className="rounded border border-border px-3 py-1 hover:bg-accent disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
