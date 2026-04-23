/**
 * SessionManager -- active (in-progress) and completed session lists on the
 * Study landing page. Completed rows use the shared SessionHistoryRow so the
 * landing page and the scoped per-doc/per-enclave history stay in sync.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
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
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  BulkActionBar,
} from "@/components/study/SessionHistory"
import {
  SessionHistoryRow,
  sessionLabel,
} from "@/components/study/SessionHistoryRow"
import {
  type StudySessionItem,
  type TeachbackResultItem,
  deleteStudySession,
  fetchSessionTeachbackResults,
  fetchSessions,
} from "@/lib/studyApi"

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

// ---------------------------------------------------------------------------
// ActiveSessionCard -- for incomplete teach-back sessions (landing page hero)
// ---------------------------------------------------------------------------

interface ActiveSessionCardProps {
  session: StudySessionItem
  onContinue: (sessionId: string, documentId: string | null, collectionId: string | null) => void
  onDelete: (sessionId: string) => void
  isDeleting: boolean
}

function ActiveSessionCard({
  session,
  onContinue,
  onDelete,
  isDeleting,
}: ActiveSessionCardProps) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const { data: teachbackResults, isLoading: tbLoading } = useQuery<
    TeachbackResultItem[]
  >({
    queryKey: ["session-teachback-results", session.id],
    queryFn: () => fetchSessionTeachbackResults(session.id),
    enabled: expanded,
  })

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-violet-200 bg-gradient-to-br from-violet-50/50 to-background p-5 shadow-sm transition-all hover:shadow-md dark:border-violet-800 dark:from-violet-950/20">
      <div
        className="flex cursor-pointer items-start justify-between"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <MessageSquare size={16} className="text-violet-500" />
            <span className="text-xs font-semibold uppercase tracking-wider text-violet-600 dark:text-violet-400">
              Teach-back -- In Progress
            </span>
          </div>
          <span className="text-sm font-medium text-foreground">
            {sessionLabel(session)}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock size={12} />
          {formatDate(session.started_at)}
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
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
      </div>

      {expanded && (
        <div className="rounded-lg border border-border bg-background/50 p-3">
          {tbLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={12} className="animate-spin" />
              Loading contents...
            </div>
          ) : !teachbackResults || teachbackResults.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No questions answered yet in this session.
            </p>
          ) : (
            <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-xs text-foreground">
              {teachbackResults.map((r) => (
                <li key={r.id}>
                  <span className="text-foreground">{r.question}</span>
                  {r.score != null && (
                    <span className="ml-2 text-[10px] text-muted-foreground">
                      ({r.score}/100)
                    </span>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={() => onContinue(session.id, session.document_id, session.collection_id)}
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
              className="rounded bg-red-600 px-2 py-0.5 text-xs text-white hover:bg-red-700 disabled:opacity-50"
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
// SessionManager -- main export
// ---------------------------------------------------------------------------

interface SessionManagerProps {
  onContinueTeachback: (sessionId: string, documentId: string | null, collectionId: string | null) => void
}

export function SessionManager({ onContinueTeachback }: SessionManagerProps) {
  const [tab, setTab] = useState<"active" | "completed">("active")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [completedPage, setCompletedPage] = useState(1)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const queryClient = useQueryClient()

  const { data: activeSessions, isLoading: activeLoading } = useQuery({
    queryKey: ["study-sessions-active"],
    queryFn: () =>
      fetchSessions(1, 20, { mode: "teachback", status: "incomplete" }),
    staleTime: 10_000,
  })

  const { data: completedSessions, isLoading: completedLoading } = useQuery({
    queryKey: ["study-sessions-completed", completedPage],
    queryFn: () =>
      fetchSessions(completedPage, 20, { mode: "teachback", status: "complete" }),
    enabled: tab === "completed",
    // Poll while any completed row still has evaluations in flight. This
    // catches the case where a user exited a session mid-evaluation and the
    // background scorer is still working.
    refetchInterval: (query) => {
      if (tab !== "completed") return false
      const items = query.state.data?.items ?? []
      return items.some((s) => s.has_pending_evaluations) ? 2_000 : false
    },
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

  const bulkDeleteMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      const results = await Promise.allSettled(ids.map(deleteStudySession))
      const failed = results.filter((r) => r.status === "rejected").length
      return { total: ids.length, failed }
    },
    onSuccess: ({ total, failed }) => {
      queryClient.invalidateQueries({ queryKey: ["study-sessions-active"] })
      queryClient.invalidateQueries({ queryKey: ["study-sessions-completed"] })
      setSelectedIds(new Set())
      setConfirmBulkDelete(false)
      if (failed === 0) {
        toast.success(`Deleted ${total} session${total === 1 ? "" : "s"}`)
      } else {
        toast.error(`Deleted ${total - failed}/${total}; ${failed} failed`)
      }
    },
    onError: () => {
      toast.error("Bulk delete failed")
      setConfirmBulkDelete(false)
    },
  })

  const activeItems = activeSessions?.items ?? []
  const completedItems = completedSessions?.items ?? []
  const completedTotal = completedSessions?.total ?? 0
  const completedTotalPages = Math.ceil(completedTotal / 20)

  const allOnPageSelected =
    completedItems.length > 0 &&
    completedItems.every((s) => selectedIds.has(s.id))

  const toggleSelectAll = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allOnPageSelected) {
        completedItems.forEach((s) => next.delete(s.id))
      } else {
        completedItems.forEach((s) => next.add(s.id))
      }
      return next
    })
  }

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-1 self-start rounded-lg bg-muted/50 p-1">
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

      {tab === "active" && (
        <div className="flex flex-col gap-3">
          {activeLoading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              Loading active sessions...
            </div>
          ) : activeItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-8 text-center">
              <MessageSquare
                size={28}
                className="mx-auto mb-3 text-muted-foreground/30"
              />
              <p className="text-sm text-muted-foreground">
                No active teach-back sessions.
              </p>
              <p className="mt-1 text-xs text-muted-foreground/70">
                Start a new teach-back session to practice explaining concepts
                in your own words.
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

      {tab === "completed" && (
        <div className="flex flex-col gap-3">
          {completedLoading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              Loading session history...
            </div>
          ) : completedItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-8 text-center">
              <CalendarDays
                size={28}
                className="mx-auto mb-3 text-muted-foreground/30"
              />
              <p className="text-sm text-muted-foreground">
                No completed sessions yet. Finish a study session to see it
                here.
              </p>
            </div>
          ) : (
            <>
              <BulkActionBar
                allSelected={allOnPageSelected}
                onToggleAll={toggleSelectAll}
                selectedCount={selectedIds.size}
                confirming={confirmBulkDelete}
                onRequestConfirm={() => setConfirmBulkDelete(true)}
                onCancelConfirm={() => setConfirmBulkDelete(false)}
                onConfirm={() =>
                  bulkDeleteMutation.mutate(Array.from(selectedIds))
                }
                isDeleting={bulkDeleteMutation.isPending}
              />
              {completedItems.map((sess) => (
                <SessionHistoryRow
                  key={sess.id}
                  session={sess}
                  isExpanded={expandedId === sess.id}
                  onToggle={() =>
                    setExpandedId(expandedId === sess.id ? null : sess.id)
                  }
                  isSelected={selectedIds.has(sess.id)}
                  onToggleSelect={() => toggleSelect(sess.id)}
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
                    onClick={() =>
                      setCompletedPage((p) =>
                        Math.min(completedTotalPages, p + 1),
                      )
                    }
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
