/**
 * CollectionTree -- collapsible 2-level collection tree for the Notes sidebar.
 *
 * Data: GET /collections/tree -> list[CollectionTreeItem]
 * Each item: colored square dot, chevron (if children), name, note_count pill.
 *
 * Interactions:
 *   Click item     -> setActiveCollectionId in useAppStore
 *   Double-click   -> inline rename input; PUT /collections/{id} on Enter/blur
 *   Pencil icon    -> inline rename input
 *   Trash icon     -> confirm Dialog; DELETE /collections/{id} on confirm
 *   Drag-over/drop -> fires POST /collections/{id}/notes via onDrop prop
 *
 * States: loading (3 skeleton lines), empty (placeholder), error (retry).
 */

import { ChevronDown, ChevronRight, Download, Pencil, Settings, Trash2 } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { API_BASE } from "@/lib/config"
import { useAppStore } from "@/store"
import type { CollectionTreeItem } from "@/lib/collectionUtils"
import { flattenCollectionTree } from "@/lib/collectionUtils"
import { CollectionHealthPanel } from "@/components/CollectionHealthPanel"

// Re-export for consumers that only need the type.
export type { CollectionTreeItem }
export { flattenCollectionTree }

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchCollectionTree(): Promise<CollectionTreeItem[]> {
  const res = await fetch(`${API_BASE}/collections/tree`)
  if (!res.ok) throw new Error(`GET /collections/tree failed: ${res.status}`)
  return res.json() as Promise<CollectionTreeItem[]>
}

async function renameCollection(id: string, name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new Error(`PUT /collections/${id} failed: ${res.status}`)
}

async function deleteCollection(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204)
    throw new Error(`DELETE /collections/${id} failed: ${res.status}`)
}

async function addNoteToCollection(collectionId: string, noteId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/collections/${collectionId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note_ids: [noteId] }),
  })
  if (!res.ok) throw new Error(`POST /collections/${collectionId}/notes failed: ${res.status}`)
}

// ---------------------------------------------------------------------------
// Single tree item row
// ---------------------------------------------------------------------------

interface CollectionTreeItemRowProps {
  item: CollectionTreeItem
  depth: number
  isExpanded: boolean
  onToggleExpand: () => void
  isActive: boolean
  onSelect: () => void
}

function CollectionTreeItemRow({
  item,
  depth,
  isExpanded,
  onToggleExpand,
  isActive,
  onSelect,
}: CollectionTreeItemRowProps) {
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(item.name)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [healthOpen, setHealthOpen] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const activeCollectionId = useAppStore((s) => s.activeCollectionId)
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)

  const renameMut = useMutation({
    mutationFn: (name: string) => renameCollection(item.id, name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["collections-tree"] })
      setRenaming(false)
    },
    onError: () => setRenaming(false),
  })

  const deleteMut = useMutation({
    mutationFn: () => deleteCollection(item.id),
    onSuccess: () => {
      if (activeCollectionId === item.id) setActiveCollectionId(null)
      void qc.invalidateQueries({ queryKey: ["collections-tree"] })
      void qc.invalidateQueries({ queryKey: ["notes"] })
      setConfirmDelete(false)
    },
  })

  const dropMut = useMutation({
    mutationFn: (noteId: string) => addNoteToCollection(item.id, noteId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notes"] })
      void qc.invalidateQueries({ queryKey: ["collections-tree"] })
    },
  })

  function commitRename() {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== item.name) {
      renameMut.mutate(trimmed)
    } else {
      setRenaming(false)
    }
  }

  function startRename() {
    setRenameValue(item.name)
    setRenaming(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  async function handleExport(format: "markdown" | "anki") {
    setExportMenuOpen(false)
    setExportLoading(true)
    const toastId = toast.loading(
      format === "markdown" ? "Preparing Markdown vault..." : "Preparing Anki deck..."
    )
    try {
      const url = `${API_BASE}/collections/${item.id}/export?format=${format}`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`Export failed: ${res.status}`)
      const blob = await res.blob()
      const disposition = res.headers.get("content-disposition") ?? ""
      const match = /filename=([^\s;]+)/.exec(disposition)
      const filename = match ? match[1] : format === "markdown" ? "vault.zip" : "deck.apkg"
      const a = document.createElement("a")
      a.href = URL.createObjectURL(blob)
      a.download = filename
      a.click()
      URL.revokeObjectURL(a.href)
      // Check for no-flashcards warning from backend
      const warning = res.headers.get("x-luminary-warning")
      if (warning) {
        toast.warning(warning, { id: toastId })
      } else {
        toast.success(
          format === "markdown" ? "Markdown vault downloaded" : "Anki deck downloaded",
          { id: toastId }
        )
      }
    } catch (err) {
      toast.error(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`, {
        id: toastId,
      })
    } finally {
      setExportLoading(false)
    }
  }

  const hasChildren = item.children.length > 0
  const paddingLeft = depth * 12 + 8

  return (
    <>
      <div
        className={`group flex items-center gap-1 rounded px-2 py-1 text-sm cursor-pointer transition-colors ${
          isActive
            ? "bg-accent font-medium text-foreground"
            : isDragOver
              ? "bg-accent/50"
              : "text-muted-foreground hover:bg-accent/60"
        }`}
        style={{ paddingLeft }}
        onClick={() => {
          if (!renaming) onSelect()
        }}
        onDoubleClick={() => startRename()}
        draggable={false}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setIsDragOver(false)
          const noteId = e.dataTransfer.getData("text/plain")
          if (noteId) dropMut.mutate(noteId)
        }}
      >
        {/* Expand/collapse chevron */}
        <button
          type="button"
          className="shrink-0 text-muted-foreground"
          onClick={(e) => {
            e.stopPropagation()
            if (hasChildren) onToggleExpand()
          }}
          style={{ visibility: hasChildren ? "visible" : "hidden" }}
        >
          {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>

        {/* Colored dot */}
        <span
          className="shrink-0 h-2.5 w-2.5 rounded-sm"
          style={{ backgroundColor: item.color }}
        />

        {/* Name or inline rename input */}
        {renaming ? (
          <input
            ref={inputRef}
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                commitRename()
              }
              if (e.key === "Escape") {
                setRenaming(false)
              }
            }}
            onBlur={commitRename}
            onClick={(e) => e.stopPropagation()}
            className="flex-1 min-w-0 rounded border border-primary bg-background px-1 text-xs text-foreground focus:outline-none"
          />
        ) : (
          <span className="flex-1 min-w-0 truncate text-sm">{item.name}</span>
        )}

        {/* Note count pill */}
        {!renaming && (
          <span className="ml-auto shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            {item.note_count}
          </span>
        )}

        {/* Action icons — shown on hover */}
        {!renaming && (
          <div className="hidden group-hover:flex items-center gap-0.5 ml-1">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setHealthOpen(true)
              }}
              className="rounded p-0.5 hover:bg-accent hover:text-foreground"
              title="Collection Health"
            >
              <Settings size={11} />
            </button>
            {/* Export submenu trigger */}
            <div className="relative">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  setExportMenuOpen((v) => !v)
                }}
                disabled={exportLoading}
                className="rounded p-0.5 hover:bg-accent hover:text-foreground disabled:opacity-50"
                title="Export"
              >
                <Download size={11} />
              </button>
              {exportMenuOpen && (
                <div
                  className="absolute right-0 top-full mt-0.5 z-50 min-w-[140px] rounded border border-border bg-popover py-1 shadow-md"
                  onMouseLeave={() => setExportMenuOpen(false)}
                >
                  <button
                    type="button"
                    className="w-full px-3 py-1 text-left text-xs hover:bg-accent"
                    onClick={(e) => {
                      e.stopPropagation()
                      void handleExport("markdown")
                    }}
                  >
                    Markdown Vault (.zip)
                  </button>
                  <button
                    type="button"
                    className="w-full px-3 py-1 text-left text-xs hover:bg-accent"
                    onClick={(e) => {
                      e.stopPropagation()
                      void handleExport("anki")
                    }}
                  >
                    Anki Deck (.apkg)
                  </button>
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                startRename()
              }}
              className="rounded p-0.5 hover:bg-accent hover:text-foreground"
              title="Rename"
            >
              <Pencil size={11} />
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(true)
              }}
              className="rounded p-0.5 hover:bg-accent hover:text-destructive"
              title="Delete"
            >
              <Trash2 size={11} />
            </button>
          </div>
        )}
      </div>

      {/* Collection health panel */}
      <CollectionHealthPanel
        open={healthOpen}
        collectionId={item.id}
        onClose={() => setHealthOpen(false)}
      />

      {/* Delete confirm dialog */}
      <Dialog open={confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete collection?</DialogTitle>
            <DialogDescription>
              Delete &ldquo;{item.name}&rdquo;? Notes are not deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button
              onClick={() => setConfirmDelete(false)}
              className="rounded border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => deleteMut.mutate()}
              disabled={deleteMut.isPending}
              className="rounded bg-destructive px-3 py-1.5 text-sm text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              Delete
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ---------------------------------------------------------------------------
// CollectionTree
// ---------------------------------------------------------------------------

export function CollectionTree() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const activeCollectionId = useAppStore((s) => s.activeCollectionId)
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)

  const {
    data: tree,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: fetchCollectionTree,
    staleTime: 30_000,
  })

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-1">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-7 w-full rounded" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        <span>Could not load collections</span>
        <button
          onClick={() => void refetch()}
          className="self-start rounded border border-amber-300 bg-white px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-50"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!tree || tree.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1 py-4 text-center text-xs text-muted-foreground">
        <span>Create your first collection</span>
        <span className="text-muted-foreground/60">using the + button below</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-0.5">
      {tree.map((item) => (
        <div key={item.id}>
          <CollectionTreeItemRow
            item={item}
            depth={0}
            isExpanded={expanded.has(item.id)}
            onToggleExpand={() => toggleExpand(item.id)}
            isActive={activeCollectionId === item.id}
            onSelect={() =>
              setActiveCollectionId(activeCollectionId === item.id ? null : item.id)
            }
          />
          {expanded.has(item.id) &&
            item.children.map((child) => (
              <CollectionTreeItemRow
                key={child.id}
                item={child}
                depth={1}
                isExpanded={false}
                onToggleExpand={() => {}}
                isActive={activeCollectionId === child.id}
                onSelect={() =>
                  setActiveCollectionId(activeCollectionId === child.id ? null : child.id)
                }
              />
            ))}
        </div>
      ))}
    </div>
  )
}
