/**
 * NormalizationDrawer -- review and accept/reject tag merge suggestions.
 *
 * Opened after POST /tags/normalization/scan completes.
 * Fetches GET /tags/normalization/suggestions on open.
 * Each row: tag_a chip -- tag_b chip, similarity %, notes affected count,
 *   Accept (Check) and Reject (X) buttons.
 *
 * States:
 *   loading     -- skeleton rows
 *   empty       -- "No duplicate tags found"
 *   error       -- inline error with Retry
 *   all-resolved -- "All suggestions resolved" footer
 */

import { Check, X } from "lucide-react"
import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TagInfo {
  id: string
  display_name: string
  note_count: number
}

interface MergeSuggestion {
  id: string
  tag_a: TagInfo
  tag_b: TagInfo
  similarity: number
  suggested_canonical_id: string
  status: string
}

type RowState = "pending" | "accepting" | "accepted" | "rejecting" | "rejected" | "error"

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchSuggestions(): Promise<MergeSuggestion[]> {
  const res = await fetch(`${API_BASE}/tags/normalization/suggestions`)
  if (!res.ok) throw new Error(`GET /tags/normalization/suggestions failed: ${res.status}`)
  return res.json() as Promise<MergeSuggestion[]>
}

async function acceptSuggestion(id: string): Promise<{ affected_notes: number }> {
  const res = await fetch(`${API_BASE}/tags/normalization/suggestions/${id}/accept`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`Accept failed: ${res.status}`)
  return res.json() as Promise<{ affected_notes: number }>
}

async function rejectSuggestion(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/tags/normalization/suggestions/${id}/reject`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`Reject failed: ${res.status}`)
}

// ---------------------------------------------------------------------------
// SuggestionRow
// ---------------------------------------------------------------------------

interface RowMeta {
  rowState: RowState
  affectedNotes?: number
  errorMsg?: string
}

interface SuggestionRowProps {
  suggestion: MergeSuggestion
  meta: RowMeta
  onAccept: () => void
  onReject: () => void
}

function SuggestionRow({ suggestion, meta, onAccept, onReject }: SuggestionRowProps) {
  const similarityPct = Math.round(suggestion.similarity * 100)
  const { rowState, affectedNotes, errorMsg } = meta

  if (rowState === "accepted") {
    return (
      <div className="flex items-center gap-2 rounded-md bg-green-50 px-3 py-2 text-xs text-green-800 border border-green-200">
        <Check size={14} className="shrink-0" />
        <span>
          Merged{typeof affectedNotes === "number" ? ` -- ${affectedNotes} note${affectedNotes !== 1 ? "s" : ""} updated` : ""}
        </span>
      </div>
    )
  }

  if (rowState === "rejected") {
    return null
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-border px-3 py-2">
      <div className="flex items-center gap-2 flex-wrap">
        {/* Tag chips */}
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
          {suggestion.tag_a.display_name}
        </span>
        <span className="text-xs text-muted-foreground">--</span>
        <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-800">
          {suggestion.tag_b.display_name}
        </span>

        {/* Similarity badge */}
        <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
          {similarityPct}% similar
        </span>
      </div>

      <div className="flex items-center gap-2">
        {/* Notes affected */}
        <span className="flex-1 text-xs text-muted-foreground">
          {suggestion.tag_a.note_count + suggestion.tag_b.note_count} notes affected
        </span>

        {/* Error message */}
        {rowState === "error" && errorMsg && (
          <span className="text-xs text-red-600">{errorMsg}</span>
        )}

        {/* Action buttons */}
        {(rowState === "pending" || rowState === "error") && (
          <>
            <button
              type="button"
              onClick={onReject}
              className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              title="Reject suggestion"
            >
              <X size={12} />
            </button>
            <button
              type="button"
              onClick={onAccept}
              className="flex items-center gap-1 rounded bg-green-600 px-2 py-1 text-xs text-white hover:bg-green-700"
              title="Accept and merge tags"
            >
              <Check size={12} />
            </button>
          </>
        )}

        {/* In-flight spinner */}
        {(rowState === "accepting" || rowState === "rejecting") && (
          <span className="text-xs text-muted-foreground animate-pulse">
            {rowState === "accepting" ? "Merging..." : "Rejecting..."}
          </span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// NormalizationDrawer
// ---------------------------------------------------------------------------

interface NormalizationDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function NormalizationDrawer({ open, onOpenChange }: NormalizationDrawerProps) {
  const queryClient = useQueryClient()

  // Row state machine: pending -> accepting/rejecting -> accepted/rejected/error
  const [rowMeta, setRowMeta] = useState<Record<string, RowMeta>>({})

  const {
    data: suggestions,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["normalization-suggestions"],
    queryFn: fetchSuggestions,
    enabled: open,
    staleTime: 0,
  })

  function getRowMeta(id: string): RowMeta {
    return rowMeta[id] ?? { rowState: "pending" }
  }

  function setRow(id: string, meta: RowMeta) {
    setRowMeta((prev) => ({ ...prev, [id]: meta }))
  }

  async function handleAccept(suggestion: MergeSuggestion) {
    setRow(suggestion.id, { rowState: "accepting" })
    try {
      const result = await acceptSuggestion(suggestion.id)
      setRow(suggestion.id, { rowState: "accepted", affectedNotes: result.affected_notes })
      // Invalidate tags tree so CollectionTree/TagTree refreshes
      await queryClient.invalidateQueries({ queryKey: ["tags-tree"] })
      await queryClient.invalidateQueries({ queryKey: ["tags-graph"] })
    } catch {
      setRow(suggestion.id, { rowState: "error", errorMsg: "Accept failed" })
    }
  }

  async function handleReject(suggestion: MergeSuggestion) {
    setRow(suggestion.id, { rowState: "rejecting" })
    try {
      await rejectSuggestion(suggestion.id)
      setRow(suggestion.id, { rowState: "rejected" })
    } catch {
      setRow(suggestion.id, { rowState: "error", errorMsg: "Reject failed" })
    }
  }

  const allResolved =
    suggestions != null &&
    suggestions.length > 0 &&
    suggestions.every((s) => {
      const state = getRowMeta(s.id).rowState
      return state === "accepted" || state === "rejected"
    })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Tag Normalization Suggestions</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-2 max-h-[60vh] overflow-y-auto py-1">
          {isLoading && (
            <>
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-md" />
              ))}
            </>
          )}

          {isError && (
            <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <span>Could not load suggestions</span>
              <button
                onClick={() => void refetch()}
                className="self-start rounded border border-amber-300 bg-white px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-50"
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading && !isError && suggestions != null && suggestions.length === 0 && (
            <div className="py-6 text-center text-sm text-muted-foreground">
              No duplicate tags found
            </div>
          )}

          {!isLoading &&
            !isError &&
            suggestions?.map((s) => {
              const meta = getRowMeta(s.id)
              if (meta.rowState === "rejected") return null
              return (
                <SuggestionRow
                  key={s.id}
                  suggestion={s}
                  meta={meta}
                  onAccept={() => void handleAccept(s)}
                  onReject={() => void handleReject(s)}
                />
              )
            })}

          {allResolved && (
            <div className="mt-2 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800 text-center">
              All suggestions resolved -- tags are clean.
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
