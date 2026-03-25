/**
 * TagManagementPanel -- modal dialog for rename, re-parent, and merge of a tag.
 *
 * Actions:
 *   Rename:    PUT /tags/{id} { display_name }
 *   Set parent: PUT /tags/{id} { parent_tag }
 *   Merge into: POST /tags/merge { source_tag_id, target_tag_id }
 *               Shows '{n} notes updated' toast on success; error toast on failure.
 *
 * Merge is atomic on the backend -- if any note update fails, all changes roll back.
 */

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { API_BASE } from "@/lib/config"
import type { TagTreeItem } from "@/components/TagTree"

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function renameTag(id: string, displayName: string): Promise<void> {
  const res = await fetch(`${API_BASE}/tags/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  })
  if (!res.ok) throw new Error(`PUT /tags/${id} failed: ${res.status}`)
}

async function reparentTag(id: string, parentTag: string | null): Promise<void> {
  const res = await fetch(`${API_BASE}/tags/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parent_tag: parentTag }),
  })
  if (!res.ok) throw new Error(`PUT /tags/${id} failed: ${res.status}`)
}

async function mergeTags(sourceTagId: string, targetTagId: string): Promise<{ affected_notes: number }> {
  const res = await fetch(`${API_BASE}/tags/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_tag_id: sourceTagId, target_tag_id: targetTagId }),
  })
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new Error(data.detail ?? `POST /tags/merge failed: ${res.status}`)
  }
  return res.json() as Promise<{ affected_notes: number }>
}

async function fetchFlatTags(): Promise<{ id: string; display_name: string }[]> {
  const res = await fetch(`${API_BASE}/tags`)
  if (!res.ok) return []
  return res.json() as Promise<{ id: string; display_name: string }[]>
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TagManagementPanelProps {
  tag: TagTreeItem
  onClose: () => void
}

export function TagManagementPanel({ tag, onClose }: TagManagementPanelProps) {
  const [renameValue, setRenameValue] = useState(tag.display_name)
  const [mergeTarget, setMergeTarget] = useState("")
  const [mergeQuery, setMergeQuery] = useState("")
  const qc = useQueryClient()

  const { data: allTags = [] } = useQuery({
    queryKey: ["tags-flat"],
    queryFn: fetchFlatTags,
    staleTime: 30_000,
  })

  // Filter merge autocomplete results
  const mergeOptions = allTags.filter(
    (t) => t.id !== tag.id && (
      mergeQuery === "" ||
      t.id.toLowerCase().includes(mergeQuery.toLowerCase()) ||
      t.display_name.toLowerCase().includes(mergeQuery.toLowerCase())
    )
  ).slice(0, 10)

  const [selectedParent, setSelectedParent] = useState<string>(tag.parent_tag ?? "")

  const renameMut = useMutation({
    mutationFn: () => renameTag(tag.id, renameValue),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tags-tree"] })
      void qc.invalidateQueries({ queryKey: ["tags-flat"] })
      toast.success("Tag renamed")
      onClose()
    },
    onError: (err: Error) => toast.error(`Rename failed: ${err.message}`),
  })

  const reparentMut = useMutation({
    mutationFn: () => reparentTag(tag.id, selectedParent || null),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tags-tree"] })
      void qc.invalidateQueries({ queryKey: ["tags-flat"] })
      toast.success("Parent updated")
      onClose()
    },
    onError: (err: Error) => toast.error(`Re-parent failed: ${err.message}`),
  })

  const mergeMut = useMutation({
    mutationFn: () => mergeTags(tag.id, mergeTarget),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: ["tags-tree"] })
      void qc.invalidateQueries({ queryKey: ["tags-flat"] })
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["notes-groups"] })
      toast.success(`${data.affected_notes} notes updated`)
      onClose()
    },
    onError: (err: Error) => toast.error(`Merge failed: ${err.message}`),
  })

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Manage tag: {tag.display_name}</DialogTitle>
          <DialogDescription className="sr-only">
            Rename, re-parent, or merge this tag
          </DialogDescription>
        </DialogHeader>

        {/* Rename section */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-foreground">Rename</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && renameValue.trim() && renameValue !== tag.display_name) {
                  renameMut.mutate()
                }
              }}
              className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button
              onClick={() => renameMut.mutate()}
              disabled={
                renameMut.isPending ||
                !renameValue.trim() ||
                renameValue === tag.display_name
              }
              className="flex items-center gap-1 rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {renameMut.isPending && <Loader2 size={11} className="animate-spin" />}
              Save
            </button>
          </div>
        </div>

        {/* Set parent section */}
        <div className="flex flex-col gap-1.5 mt-3">
          <label className="text-xs font-medium text-foreground">Set Parent</label>
          <div className="flex gap-2">
            <select
              value={selectedParent}
              onChange={(e) => setSelectedParent(e.target.value)}
              className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">(none -- top-level tag)</option>
              {allTags
                .filter((t) => t.id !== tag.id)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.display_name}
                  </option>
                ))}
            </select>
            <button
              onClick={() => reparentMut.mutate()}
              disabled={
                reparentMut.isPending ||
                selectedParent === (tag.parent_tag ?? "")
              }
              className="flex items-center gap-1 rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {reparentMut.isPending && <Loader2 size={11} className="animate-spin" />}
              Apply
            </button>
          </div>
        </div>

        {/* Merge section */}
        <div className="flex flex-col gap-1.5 mt-3">
          <label className="text-xs font-medium text-foreground">Merge into</label>
          <p className="text-xs text-muted-foreground">
            All notes tagged &ldquo;{tag.display_name}&rdquo; will be re-tagged with the target.
            This action cannot be undone.
          </p>
          <div className="relative">
            <input
              type="text"
              value={mergeQuery}
              onChange={(e) => {
                setMergeQuery(e.target.value)
                setMergeTarget("")
              }}
              placeholder="Search tags..."
              className="w-full rounded border border-border bg-background px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            {mergeQuery && mergeOptions.length > 0 && (
              <div className="absolute z-10 mt-1 w-full rounded border border-border bg-popover shadow-md">
                {mergeOptions.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => {
                      setMergeTarget(t.id)
                      setMergeQuery(t.id)
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent"
                  >
                    <span className="font-medium text-foreground">{t.display_name}</span>
                    <span className="text-xs text-muted-foreground">{t.id}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          {mergeTarget && (
            <button
              onClick={() => mergeMut.mutate()}
              disabled={mergeMut.isPending}
              className="flex items-center justify-center gap-1.5 rounded bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              {mergeMut.isPending && <Loader2 size={11} className="animate-spin" />}
              Merge into &ldquo;{mergeTarget}&rdquo;
            </button>
          )}
        </div>

        <DialogFooter className="mt-2">
          <button
            onClick={onClose}
            className="rounded border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
