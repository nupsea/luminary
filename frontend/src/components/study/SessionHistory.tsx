/**
 * SessionHistory -- scoped list of past runs for a collection or a document.
 *
 * Both modes, not teach-back alone. The docked Practice face and the Study page
 * are two views of one document's practice, and a list that hides recall runs
 * makes them disagree about what happened: the reader offers to pick a recall
 * run back up while the Study page shows no such run exists. Resume carries the
 * row's own mode so the host reopens the run that was clicked rather than the
 * one it prefers.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { History, Loader2, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { SessionHistoryRow } from "@/components/study/SessionHistoryRow"
import { deleteStudySession, fetchSessions } from "@/lib/studyApi"
import type { StudyMode } from "@/lib/studySessionService"

type Scope =
  | { kind: "collection"; id: string }
  | { kind: "document"; id: string }

interface SessionHistoryProps {
  scope: Scope
  onResume: (sessionId: string, mode: StudyMode) => void
  title?: string
  /** Told after a delete, so a host holding its own view of these runs refreshes. */
  onChanged?: () => void
}

export function SessionHistory({
  scope,
  onResume,
  title = "Session History",
  onChanged,
}: SessionHistoryProps) {
  const queryClient = useQueryClient()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)

  const queryKey = ["scoped-sessions", scope.kind, scope.id] as const

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      fetchSessions(1, 50, {
        collectionId: scope.kind === "collection" ? scope.id : undefined,
        documentId: scope.kind === "document" ? scope.id : undefined,
      }),
    staleTime: 5_000,
    // Keep refreshing while any row still has teach-back evaluations in flight
    // (e.g. user exited a session mid-evaluation). Stops once all resolve.
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      return items.some((s) => s.has_pending_evaluations) ? 2_000 : false
    },
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({
      queryKey: ["scoped-sessions", scope.kind, scope.id],
    })
    queryClient.invalidateQueries({ queryKey: ["study-sessions-active"] })
    queryClient.invalidateQueries({ queryKey: ["study-sessions-completed"] })
    onChanged?.()
  }

  const deleteMutation = useMutation({
    mutationFn: deleteStudySession,
    onSuccess: () => {
      invalidateAll()
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
      invalidateAll()
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

  const sessions = data?.items ?? []
  const hasAny = sessions.length > 0
  const scopeLabel =
    scope.kind === "collection" ? "this collection" : "this document"

  const allSelected =
    sessions.length > 0 && sessions.every((s) => selectedIds.has(s.id))

  const toggleSelectAll = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allSelected) {
        sessions.forEach((s) => next.delete(s.id))
      } else {
        sessions.forEach((s) => next.add(s.id))
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
    <div className="flex flex-col gap-4">
      <h3 className="flex items-center gap-2 font-semibold text-foreground">
        <History size={18} className="text-primary" />
        {title}
      </h3>

      {isLoading ? (
        <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          Loading sessions...
        </div>
      ) : !hasAny ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 px-6 py-8 text-center">
          <History size={24} className="mx-auto mb-2 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">
            No practice runs yet for {scopeLabel}.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <BulkActionBar
            allSelected={allSelected}
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
          {sessions.map((s) => (
            <SessionHistoryRow
              key={s.id}
              session={s}
              isExpanded={expandedId === s.id}
              onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
              isSelected={selectedIds.has(s.id)}
              onToggleSelect={() => toggleSelect(s.id)}
              onDelete={(id) => deleteMutation.mutate(id)}
              isDeleting={deleteMutation.isPending}
              onResume={(id) => onResume(id, s.mode === "teachback" ? "teachback" : "flashcard")}
              showChevron={false}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface BulkActionBarProps {
  allSelected: boolean
  onToggleAll: () => void
  selectedCount: number
  confirming: boolean
  onRequestConfirm: () => void
  onCancelConfirm: () => void
  onConfirm: () => void
  isDeleting: boolean
}

export function BulkActionBar({
  allSelected,
  onToggleAll,
  selectedCount,
  confirming,
  onRequestConfirm,
  onCancelConfirm,
  onConfirm,
  isDeleting,
}: BulkActionBarProps) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs">
      <label className="flex cursor-pointer items-center gap-2 text-muted-foreground">
        <input
          type="checkbox"
          checked={allSelected}
          onChange={onToggleAll}
          className="h-4 w-4 cursor-pointer accent-violet-600"
        />
        Select all
      </label>
      {selectedCount > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">
            {selectedCount} selected
          </span>
          {!confirming ? (
            <button
              onClick={onRequestConfirm}
              className="flex items-center gap-1 rounded bg-red-600 px-2.5 py-1 font-semibold text-white hover:bg-red-700"
            >
              <Trash2 size={12} />
              Delete selected
            </button>
          ) : (
            <div className="flex items-center gap-1.5">
              <span className="text-red-600">
                Delete {selectedCount} session
                {selectedCount === 1 ? "" : "s"}?
              </span>
              <button
                onClick={onConfirm}
                disabled={isDeleting}
                className="rounded bg-red-600 px-2 py-0.5 font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {isDeleting ? "Deleting..." : "Yes"}
              </button>
              <button
                onClick={onCancelConfirm}
                className="rounded border border-border px-2 py-0.5 hover:bg-accent"
              >
                No
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
