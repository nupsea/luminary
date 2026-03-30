/**
 * OrganizationPlanDialog -- full-page dialog showing all cluster suggestions
 * as an editable Organization Plan.
 *
 * Features:
 * - Header: "Found N groups in M notes" with average confidence
 * - Each group: editable name, note list with excerpts, confidence bar, include/exclude checkbox
 * - Native drag-and-drop to move notes between groups
 * - "Apply Plan" -> POST /notes/cluster/suggestions/batch-accept
 * - "Dismiss" -> reject all suggestions individually
 */

import { useState, useCallback } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Check, GripVertical, X } from "lucide-react"
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NotePreview {
  note_id: string
  excerpt: string
}

export interface ClusterSuggestion {
  id: string
  suggested_name: string
  note_ids: string[]
  note_count: number
  confidence_score: number
  status: string
  created_at: string
  previews: NotePreview[]
}

interface GroupState {
  suggestion_id: string
  name: string
  included: boolean
  confidence_score: number
  notes: NotePreview[]
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  suggestions: ClusterSuggestion[]
  onApplied: () => void
  onDismissed: () => void
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function batchAccept(
  items: { suggestion_id: string; name_override: string | null; note_ids: string[] }[],
): Promise<{ collection_ids: string[] }> {
  const res = await fetch(`${API_BASE}/notes/cluster/suggestions/batch-accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  })
  if (!res.ok) throw new Error(`batch-accept failed: ${res.status}`)
  return res.json() as Promise<{ collection_ids: string[] }>
}

async function rejectSuggestion(id: string): Promise<void> {
  await fetch(`${API_BASE}/notes/cluster/suggestions/${id}/reject`, { method: "POST" })
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OrganizationPlanDialog({ open, onOpenChange, suggestions, onApplied, onDismissed }: Props) {
  const [groups, setGroups] = useState<GroupState[]>(() => initGroups(suggestions))
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [dragSource, setDragSource] = useState<{ groupIdx: number; noteIdx: number } | null>(null)

  // Re-init when suggestions change (dialog re-opened)
  const prevSuggestionIds = suggestions.map((s) => s.id).join(",")
  const [lastIds, setLastIds] = useState(prevSuggestionIds)
  if (prevSuggestionIds !== lastIds) {
    setLastIds(prevSuggestionIds)
    setGroups(initGroups(suggestions))
  }

  const totalNotes = groups.reduce((sum, g) => sum + g.notes.length, 0)
  const avgConfidence =
    groups.length > 0
      ? groups.reduce((sum, g) => sum + g.confidence_score, 0) / groups.length
      : 0

  const handleNameChange = useCallback((idx: number, name: string) => {
    setGroups((prev) => prev.map((g, i) => (i === idx ? { ...g, name } : g)))
  }, [])

  const handleToggleInclude = useCallback((idx: number) => {
    setGroups((prev) => prev.map((g, i) => (i === idx ? { ...g, included: !g.included } : g)))
  }, [])

  // Drag-and-drop handlers
  function handleDragStart(groupIdx: number, noteIdx: number, e: React.DragEvent) {
    setDragSource({ groupIdx, noteIdx })
    e.dataTransfer.effectAllowed = "move"
    e.dataTransfer.setData("text/plain", `${groupIdx}:${noteIdx}`)
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
  }

  function handleDrop(targetGroupIdx: number, e: React.DragEvent) {
    e.preventDefault()
    if (!dragSource) return
    if (dragSource.groupIdx === targetGroupIdx) return

    setGroups((prev) => {
      const next = prev.map((g) => ({ ...g, notes: [...g.notes] }))
      const note = next[dragSource.groupIdx].notes.splice(dragSource.noteIdx, 1)[0]
      if (note) {
        next[targetGroupIdx].notes.push(note)
      }
      return next
    })
    setDragSource(null)
  }

  async function handleApply() {
    const included = groups.filter((g) => g.included && g.notes.length > 0)
    if (included.length === 0) return

    setApplying(true)
    setApplyError(null)
    try {
      const items = included.map((g) => {
        const original = suggestions.find((s) => s.id === g.suggestion_id)
        const nameChanged = g.name !== original?.suggested_name
        // Send note_ids to persist drag-and-drop changes
        const noteIds = g.notes.map((n) => n.note_id)
        return {
          suggestion_id: g.suggestion_id,
          name_override: nameChanged ? g.name : null,
          note_ids: noteIds,
        }
      })
      await batchAccept(items)
      onApplied()
      onOpenChange(false)
    } catch {
      setApplyError("Failed to apply organization plan. Please try again.")
    } finally {
      setApplying(false)
    }
  }

  async function handleDismiss() {
    try {
      await Promise.all(suggestions.map((s) => rejectSuggestion(s.id)))
      onDismissed()
      onOpenChange(false)
    } catch {
      setApplyError("Failed to dismiss suggestions. Please try again.")
    }
  }

  const noSuggestions = suggestions.length === 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Organization Plan</DialogTitle>
          <DialogDescription>
            {noSuggestions
              ? "Your notes are already well-organized -- no grouping suggestions"
              : `Found ${groups.length} groups in ${totalNotes} notes (avg confidence: ${Math.round(avgConfidence * 100)}%)`}
          </DialogDescription>
        </DialogHeader>

        {!noSuggestions && (
          <div className="flex-1 overflow-auto space-y-3 py-2">
            {groups.map((group, gIdx) => (
              <div
                key={group.suggestion_id}
                className={`rounded-lg border p-3 transition-opacity ${!group.included ? "opacity-50" : ""}`}
                onDragOver={handleDragOver}
                onDrop={(e) => handleDrop(gIdx, e)}
              >
                {/* Group header */}
                <div className="flex items-center gap-2 mb-2">
                  <input
                    type="checkbox"
                    checked={group.included}
                    onChange={() => handleToggleInclude(gIdx)}
                    className="h-4 w-4 rounded border-border"
                  />
                  <input
                    type="text"
                    value={group.name}
                    onChange={(e) => handleNameChange(gIdx, e.target.value)}
                    className="flex-1 rounded border border-border bg-transparent px-2 py-1 text-sm font-medium focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {group.notes.length} notes
                  </span>
                </div>

                {/* Confidence bar */}
                <div className="mb-2 h-1.5 rounded bg-border">
                  <div
                    className="h-1.5 rounded bg-primary"
                    style={{ width: `${Math.round(group.confidence_score * 100)}%` }}
                  />
                </div>

                {/* Note list */}
                <div className="space-y-1">
                  {group.notes.map((note, nIdx) => (
                    <div
                      key={note.note_id}
                      draggable
                      onDragStart={(e) => handleDragStart(gIdx, nIdx, e)}
                      className="flex items-start gap-1.5 rounded px-2 py-1 text-xs hover:bg-accent/40 cursor-grab active:cursor-grabbing"
                    >
                      <GripVertical size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
                      <span className="truncate text-muted-foreground italic">
                        {note.excerpt || "(empty note)"}
                      </span>
                    </div>
                  ))}
                  {group.notes.length === 0 && (
                    <p className="px-2 py-1 text-xs text-muted-foreground">
                      No notes in this group. Drag notes here to add them.
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <DialogFooter className="gap-2">
          {applyError && (
            <p className="mr-auto text-xs text-red-500">{applyError}</p>
          )}
          <button
            onClick={() => void handleDismiss()}
            className="flex items-center gap-1 rounded px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
          >
            <X size={14} />
            Dismiss
          </button>
          {!noSuggestions && (
            <button
              onClick={() => void handleApply()}
              disabled={applying || groups.filter((g) => g.included && g.notes.length > 0).length === 0}
              className="flex items-center gap-1 rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              <Check size={14} />
              {applying ? "Applying..." : "Apply Plan"}
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function initGroups(suggestions: ClusterSuggestion[]): GroupState[] {
  return suggestions.map((s) => ({
    suggestion_id: s.id,
    name: s.suggested_name,
    included: true,
    confidence_score: s.confidence_score,
    notes: s.previews.map((p) => ({ note_id: p.note_id, excerpt: p.excerpt })),
  }))
}
