/**
 * CreateCollectionDialog -- dialog for creating a new collection.
 *
 * Fields: name (required), description, 8-swatch color picker, parent select
 * (top-level collections only -- max 2-level nesting).
 *
 * POST /collections on save. Invalidates ["collections-tree"] on success.
 */

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { apiGet, apiPost } from "@/lib/apiClient"
import type { CollectionTreeItem } from "@/lib/collectionUtils"
import { normalizeCollectionName } from "@/lib/tagUtils"

// ---------------------------------------------------------------------------
// 8 colour swatches
// ---------------------------------------------------------------------------

export const COLLECTION_COLORS = [
  "#6366F1", // indigo
  "#8B5CF6", // violet
  "#EC4899", // pink
  "#EF4444", // red
  "#F59E0B", // amber
  "#10B981", // emerald
  "#3B82F6", // blue
  "#6B7280", // gray
]

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchCollectionTree(): Promise<CollectionTreeItem[]> {
  try {
    return await apiGet<CollectionTreeItem[]>("/collections/tree")
  } catch {
    return []
  }
}

const createCollection = (payload: {
  name: string
  description: string | null
  color: string
  parent_collection_id: string | null
}): Promise<void> => apiPost("/collections", payload)

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface CreateCollectionDialogProps {
  open: boolean
  onClose: () => void
}

export function CreateCollectionDialog({ open, onClose }: CreateCollectionDialogProps) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [color, setColor] = useState(COLLECTION_COLORS[0])
  const [parentId, setParentId] = useState<string>("")
  const qc = useQueryClient()

  const { data: tree = [] } = useQuery({
    queryKey: ["collections-tree"],
    queryFn: fetchCollectionTree,
    staleTime: 30_000,
    enabled: open,
  })

  // Only top-level collections are valid parents (2-level nesting max).
  const topLevelCollections = tree

  const normalizedName = normalizeCollectionName(name)

  const createMut = useMutation({
    mutationFn: () =>
      createCollection({
        name: normalizedName,
        description: description.trim() || null,
        color,
        parent_collection_id: parentId || null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["collections-tree"] })
      handleClose()
    },
  })

  function handleClose() {
    setName("")
    setDescription("")
    setColor(COLLECTION_COLORS[0])
    setParentId("")
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>New Collection</DialogTitle>
          <DialogDescription>Organise notes into a named collection.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {/* Name */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-foreground">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Collection name"
              className="rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            {name.trim() && normalizedName !== name.trim() && (
              <span className="text-[10px] text-muted-foreground">{normalizedName}</span>
            )}
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-foreground">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description"
              rows={2}
              className="resize-none rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Color picker */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-foreground">Color</label>
            <div className="flex gap-2">
              {COLLECTION_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={`h-5 w-5 rounded-sm transition-transform ${
                    color === c ? "ring-2 ring-primary ring-offset-1 scale-110" : "hover:scale-110"
                  }`}
                  style={{ backgroundColor: c }}
                  title={c}
                />
              ))}
            </div>
          </div>

          {/* Parent select */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-foreground">Parent collection</label>
            <select
              value={parentId}
              onChange={(e) => setParentId(e.target.value)}
              className="rounded border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">None (top-level)</option>
              {topLevelCollections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {createMut.isError && (
            <p className="text-xs text-red-600">Failed to create collection. Please try again.</p>
          )}
        </div>

        <DialogFooter>
          <button
            onClick={handleClose}
            className="rounded border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={() => createMut.mutate()}
            disabled={!normalizedName || createMut.isPending}
            className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Create
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
