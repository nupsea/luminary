import { ExternalLink, Plus } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"

import { CollectionTree, DOC_DRAG_MIME } from "@/components/CollectionTree"
import { CreateCollectionDialog } from "@/components/CreateCollectionDialog"

interface LibraryCollectionsRailProps {
  selectedId: string | null
  onSelect: (id: string | null) => void
}

/**
 * The Notes sidebar's CollectionTree, wired for documents. The two rails differ
 * only in what a drop adds and in this header.
 */
export function LibraryCollectionsRail({ selectedId, onSelect }: LibraryCollectionsRailProps) {
  const [formOpen, setFormOpen] = useState(false)
  const navigate = useNavigate()

  return (
    <aside className="flex flex-col gap-3 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center justify-between">
        <h3 className="lum-eyebrow">Collections</h3>
        <div className="flex items-center gap-2">
          {selectedId && (
            <button
              onClick={() => navigate(`/collections/${selectedId}`)}
              className="flex items-center gap-1 text-[11px] text-primary hover:underline"
              title="Open collection workspace"
            >
              Open <ExternalLink size={10} />
            </button>
          )}
          {selectedId && (
            <button
              onClick={() => onSelect(null)}
              className="text-[11px] text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
            >
              Clear
            </button>
          )}
          <button
            onClick={() => setFormOpen(true)}
            className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            title="New collection"
          >
            <Plus size={12} />
          </button>
        </div>
      </div>

      <CollectionTree
        contains="document"
        memberType="document"
        dragMime={DOC_DRAG_MIME}
        selectedId={selectedId}
        onSelect={onSelect}
      />

      <CreateCollectionDialog open={formOpen} onClose={() => setFormOpen(false)} />
    </aside>
  )
}
