/**
 * TagTree -- collapsible hierarchical tag tree for the Notes sidebar.
 *
 * Data: GET /tags/tree -> list[TagTreeItem]
 * Each item: tag name, note_count pill, gear icon on hover (opens TagManagementPanel).
 *
 * Interactions:
 *   Click item -> setActiveTag in useAppStore (Notes list refetches with ?tag=)
 *   Gear icon  -> opens TagManagementPanel popover for rename/re-parent/merge
 *
 * States: loading (skeleton), empty (placeholder), error (retry).
 */

import { ChevronDown, ChevronRight, Settings2 } from "lucide-react"
import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import { TagManagementPanel } from "@/components/TagManagementPanel"
import { API_BASE } from "@/lib/config"
import { useAppStore } from "@/store"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TagTreeItem {
  id: string
  display_name: string
  parent_tag: string | null
  note_count: number
  children: TagTreeItem[]
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function fetchTagTree(): Promise<TagTreeItem[]> {
  const res = await fetch(`${API_BASE}/tags/tree`)
  if (!res.ok) throw new Error(`GET /tags/tree failed: ${res.status}`)
  return res.json() as Promise<TagTreeItem[]>
}

// ---------------------------------------------------------------------------
// Single tag row
// ---------------------------------------------------------------------------

interface TagTreeItemRowProps {
  item: TagTreeItem
  depth: number
  isExpanded: boolean
  onToggleExpand: () => void
  isActive: boolean
  onSelect: () => void
}

function TagTreeItemRow({
  item,
  depth,
  isExpanded,
  onToggleExpand,
  isActive,
  onSelect,
}: TagTreeItemRowProps) {
  const [showManage, setShowManage] = useState(false)
  const hasChildren = item.children.length > 0
  const paddingLeft = depth * 12 + 8

  return (
    <>
      <div
        className={`group flex items-center gap-1 rounded px-2 py-1 text-sm cursor-pointer transition-colors ${
          isActive
            ? "bg-accent font-medium text-foreground"
            : "text-muted-foreground hover:bg-accent/60"
        }`}
        style={{ paddingLeft }}
        onClick={onSelect}
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

        {/* Tag name */}
        <span className="flex-1 min-w-0 truncate text-sm">{item.display_name}</span>

        {/* Note count pill */}
        <span className="ml-auto shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
          {item.note_count}
        </span>

        {/* Gear icon -- shown on hover */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setShowManage(true)
          }}
          className="hidden group-hover:flex shrink-0 rounded p-0.5 hover:bg-accent hover:text-foreground"
          title="Manage tag"
        >
          <Settings2 size={11} />
        </button>
      </div>

      {/* Tag management popover */}
      {showManage && (
        <TagManagementPanel
          tag={item}
          onClose={() => setShowManage(false)}
        />
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// TagTree
// ---------------------------------------------------------------------------

export function TagTree() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const activeTag = useAppStore((s) => s.activeTag)
  const setActiveTag = useAppStore((s) => s.setActiveTag)

  const {
    data: tree,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["tags-tree"],
    queryFn: fetchTagTree,
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
        <span>Could not load tags</span>
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
        <span>Notes you save will be auto-tagged</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-0.5">
      {tree.map((item) => (
        <div key={item.id}>
          <TagTreeItemRow
            item={item}
            depth={0}
            isExpanded={expanded.has(item.id)}
            onToggleExpand={() => toggleExpand(item.id)}
            isActive={activeTag === item.id}
            onSelect={() => setActiveTag(activeTag === item.id ? null : item.id)}
          />
          {expanded.has(item.id) &&
            item.children.map((child) => (
              <TagTreeItemRow
                key={child.id}
                item={child}
                depth={1}
                isExpanded={false}
                onToggleExpand={() => {}}
                isActive={activeTag === child.id}
                onSelect={() => setActiveTag(activeTag === child.id ? null : child.id)}
              />
            ))}
        </div>
      ))}
    </div>
  )
}
