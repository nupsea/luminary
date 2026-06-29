import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"

import { Skeleton } from "@/components/ui/skeleton"
import { addDocumentToCollection, fetchCollectionTree } from "@/lib/notesApi"
import type { CollectionTreeItem } from "@/lib/collectionUtils"
import { cn } from "@/lib/utils"

const DOC_DRAG_MIME = "application/x-luminary-doc-id"

interface LibraryCollectionsRailProps {
  selectedId: string | null
  onSelect: (id: string | null) => void
}

export function LibraryCollectionsRail({ selectedId, onSelect }: LibraryCollectionsRailProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // scope=document: hide note-only collections so the Library rail stays
  // focused on doc-relevant memberships. The unscoped invalidations elsewhere
  // (queryKey starts with "collections-tree") still hit this query via the
  // default prefix-match behavior of invalidateQueries.
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["collections-tree", "contains:document"],
    queryFn: () => fetchCollectionTree("document"),
    staleTime: 30_000,
  })

  const dropMut = useMutation({
    mutationFn: ({ collectionId, docId }: { collectionId: string; docId: string }) =>
      addDocumentToCollection(collectionId, docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["collections-tree"] })
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      toast.success("Added to collection")
    },
    onError: () => toast.error("Could not add to collection"),
  })

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
        </div>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-1">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-6 w-full rounded" />
          ))}
        </div>
      )}

      {isError && (
        <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          <span>Could not load collections</span>
          <button
            onClick={() => void refetch()}
            className="self-start rounded border border-amber-300 bg-white px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-50 dark:border-amber-800 dark:bg-transparent dark:text-amber-300 dark:hover:bg-amber-900/40"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && (!data || data.length === 0) && (
        <p className="py-2 text-xs text-muted-foreground">No collections yet</p>
      )}

      {!isLoading && !isError && data && data.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {data.map((item) => (
            <RailItem
              key={item.id}
              item={item}
              depth={0}
              isExpanded={expanded.has(item.id)}
              onToggleExpand={() => toggleExpand(item.id)}
              selectedId={selectedId}
              onSelect={onSelect}
              onDropDoc={(docId) => dropMut.mutate({ collectionId: item.id, docId })}
            >
              {expanded.has(item.id) &&
                item.children.map((child) => (
                  <RailItem
                    key={child.id}
                    item={child}
                    depth={1}
                    isExpanded={false}
                    onToggleExpand={() => {}}
                    selectedId={selectedId}
                    onSelect={onSelect}
                    onDropDoc={(docId) =>
                      dropMut.mutate({ collectionId: child.id, docId })
                    }
                  />
                ))}
            </RailItem>
          ))}
        </div>
      )}
    </aside>
  )
}

interface RailItemProps {
  item: CollectionTreeItem
  depth: number
  isExpanded: boolean
  onToggleExpand: () => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  onDropDoc: (docId: string) => void
  children?: React.ReactNode
}

function RailItem({
  item,
  depth,
  isExpanded,
  onToggleExpand,
  selectedId,
  onSelect,
  onDropDoc,
  children,
}: RailItemProps) {
  const [isDragOver, setIsDragOver] = useState(false)
  const hasChildren = item.children.length > 0
  const isActive = selectedId === item.id
  const paddingLeft = depth * 12 + 4

  return (
    <>
      <button
        onClick={() => onSelect(isActive ? null : item.id)}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes(DOC_DRAG_MIME)) {
            e.preventDefault()
            e.dataTransfer.dropEffect = "copy"
            setIsDragOver(true)
          }
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          const docId = e.dataTransfer.getData(DOC_DRAG_MIME)
          setIsDragOver(false)
          if (!docId) return
          e.preventDefault()
          onDropDoc(docId)
        }}
        style={{ paddingLeft }}
        className={cn(
          "group flex items-center gap-1 rounded px-2 py-1 text-left text-sm transition-colors",
          isActive
            ? "bg-accent font-medium text-foreground"
            : isDragOver
              ? "bg-primary/10 text-foreground ring-1 ring-primary/40"
              : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
        )}
      >
        <span
          role="button"
          tabIndex={hasChildren ? 0 : -1}
          onClick={(e) => {
            if (!hasChildren) return
            e.stopPropagation()
            onToggleExpand()
          }}
          className="shrink-0 text-muted-foreground"
          style={{ visibility: hasChildren ? "visible" : "hidden" }}
        >
          {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
        <span
          className="shrink-0 h-2.5 w-2.5 rounded-sm"
          style={{ backgroundColor: item.color }}
        />
        <span className="flex-1 min-w-0 truncate">{item.name}</span>
        {item.scoped_count > 0 && (
          <span
            className="ml-auto shrink-0 rounded-full bg-blue-100/60 dark:bg-blue-900/30 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:text-blue-300"
            title={`${item.scoped_count} document${item.scoped_count === 1 ? "" : "s"} (inclusive of subcollections)`}
          >
            {item.scoped_count}
          </span>
        )}
      </button>
      {children}
    </>
  )
}
