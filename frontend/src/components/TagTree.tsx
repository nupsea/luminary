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

import { ChevronDown, ChevronRight, Settings2, Wrench, Search, X } from "lucide-react"
import { useState, useEffect, useCallback, useRef } from "react"
import { useQuery } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import { NormalizationDrawer } from "@/components/NormalizationDrawer"
import { TagManagementPanel } from "@/components/TagManagementPanel"
import { API_BASE } from "@/lib/config"
import { useAppStore } from "@/store"
import { filterTagTree, highlightMatch } from "@/lib/tagUtils"
import type { FilteredTagTreeItem } from "@/lib/tagUtils"

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
  item: FilteredTagTreeItem
  depth: number
  isExpanded: boolean
  onToggleExpand: () => void
  isActive: boolean
  onSelect: () => void
  searchQuery: string
}

function TagTreeItemRow({
  item,
  depth,
  isExpanded,
  onToggleExpand,
  isActive,
  onSelect,
  searchQuery,
}: TagTreeItemRowProps) {
  const [showManage, setShowManage] = useState(false)
  const hasChildren = item.children.length > 0
  const paddingLeft = depth * 12 + 8
  const isDimmed = searchQuery && !item.matched

  return (
    <>
      <div
        className={`group flex items-center gap-1 rounded px-2 py-1 text-sm cursor-pointer transition-colors ${
          isActive
            ? "bg-accent font-medium text-foreground"
            : isDimmed
              ? "text-muted-foreground/50 hover:bg-accent/40"
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

        {/* Tag name with optional search highlight */}
        <span className={`flex-1 min-w-0 truncate text-sm ${item.matched && searchQuery ? "font-semibold" : ""}`}>
          {searchQuery && item.matched ? (
            highlightMatch(item.display_name, searchQuery).map((seg, i) =>
              seg.highlight ? (
                <mark key={i} className="bg-yellow-200 dark:bg-yellow-800 rounded-sm px-0.5">
                  {seg.text}
                </mark>
              ) : (
                <span key={i}>{seg.text}</span>
              ),
            )
          ) : (
            item.display_name
          )}
        </span>

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

// ---------------------------------------------------------------------------
// Recursive tree renderer
// ---------------------------------------------------------------------------

function TagSubtree({
  items,
  depth,
  expanded,
  toggleExpand,
  activeTag,
  onSelect,
  searchQuery,
}: {
  items: FilteredTagTreeItem[]
  depth: number
  expanded: Set<string>
  toggleExpand: (id: string) => void
  activeTag: string | null
  onSelect: (id: string) => void
  searchQuery: string
}) {
  return (
    <>
      {items.map((item) => (
        <div key={item.id}>
          <TagTreeItemRow
            item={item}
            depth={depth}
            isExpanded={searchQuery ? true : expanded.has(item.id)}
            onToggleExpand={() => toggleExpand(item.id)}
            isActive={activeTag === item.id}
            onSelect={() => onSelect(item.id)}
            searchQuery={searchQuery}
          />
          {(searchQuery || expanded.has(item.id)) && item.children.length > 0 && (
            <TagSubtree
              items={item.children}
              depth={depth + 1}
              expanded={expanded}
              toggleExpand={toggleExpand}
              activeTag={activeTag}
              onSelect={onSelect}
              searchQuery={searchQuery}
            />
          )}
        </div>
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// Collect all matched IDs from filtered tree (for Enter key: first match)
// ---------------------------------------------------------------------------

function collectMatchedIds(items: FilteredTagTreeItem[]): string[] {
  const result: string[] = []
  for (const item of items) {
    if (item.matched) result.push(item.id)
    result.push(...collectMatchedIds(item.children))
  }
  return result
}

// ---------------------------------------------------------------------------
// TagTree
// ---------------------------------------------------------------------------

export function TagTree() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [normOpen, setNormOpen] = useState(false)
  const [scanInFlight, setScanInFlight] = useState(false)
  const activeTag = useAppStore((s) => s.activeTag)
  const setActiveTag = useAppStore((s) => s.setActiveTag)
  const setActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)

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

  const [searchQuery, setSearchQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedQuery(value), 150)
  }, [])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const filteredTree = filterTagTree(tree || [], debouncedQuery)

  function handleSelect(id: string) {
    setActiveCollectionId(null)
    setActiveTag(activeTag === id ? null : id)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && debouncedQuery) {
      const matchedIds = collectMatchedIds(filteredTree)
      if (matchedIds.length > 0) {
        handleSelect(matchedIds[0])
      }
    }
  }

  async function handleNormalize() {
    setScanInFlight(true)
    try {
      await fetch(`${API_BASE}/tags/normalization/scan`, { method: "POST" })
    } finally {
      setScanInFlight(false)
      setNormOpen(true)
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const normalizeButton = (
    <button
      type="button"
      onClick={() => void handleNormalize()}
      disabled={scanInFlight}
      className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
      title="Normalize tags (find duplicates)"
    >
      <Wrench size={12} className={scanInFlight ? "animate-spin" : ""} />
    </button>
  )

  const searchInput = (
    <div className="relative flex-1">
      <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
      <input
        type="text"
        value={searchQuery}
        onChange={(e) => handleSearchChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Search tags..."
        className="w-full rounded border border-border bg-background py-1 pl-7 pr-6 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />
      {searchQuery && (
        <button
          type="button"
          onClick={() => { setSearchQuery(""); setDebouncedQuery("") }}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
          title="Clear search"
        >
          <X size={10} />
        </button>
      )}
    </div>
  )

  if (isLoading) {
    return (
      <>
        <div className="flex items-center mb-1">{normalizeButton}</div>
        <div className="flex flex-col gap-1">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-full rounded" />
          ))}
        </div>
        <NormalizationDrawer open={normOpen} onOpenChange={setNormOpen} />
      </>
    )
  }

  if (isError) {
    return (
      <>
        <div className="flex items-center mb-1">{normalizeButton}</div>
        <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span>Could not load tags</span>
          <button
            onClick={() => void refetch()}
            className="self-start rounded border border-amber-300 bg-white px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-50"
          >
            Retry
          </button>
        </div>
        <NormalizationDrawer open={normOpen} onOpenChange={setNormOpen} />
      </>
    )
  }

  if (!tree || tree.length === 0) {
    return (
      <>
        <div className="flex items-center gap-2 mb-1">
          {searchInput}
          {normalizeButton}
        </div>
        <div className="flex flex-col items-center gap-1 py-4 text-center text-xs text-muted-foreground">
          <span>Notes you save will be auto-tagged</span>
        </div>
        <NormalizationDrawer open={normOpen} onOpenChange={setNormOpen} />
      </>
    )
  }

  const showEmptyResult = debouncedQuery && filteredTree.length === 0

  return (
    <>
      <div className="flex items-center gap-2 mb-1">
        {searchInput}
        {normalizeButton}
      </div>
      {showEmptyResult ? (
        <div className="flex flex-col items-center gap-1 py-4 text-center text-xs text-muted-foreground">
          <span>No tags matching &ldquo;{debouncedQuery}&rdquo;</span>
        </div>
      ) : (
        <div className="flex flex-col gap-0.5">
          <TagSubtree
            items={filteredTree}
            depth={0}
            expanded={expanded}
            toggleExpand={toggleExpand}
            activeTag={activeTag}
            onSelect={handleSelect}
            searchQuery={debouncedQuery}
          />
        </div>
      )}
      <NormalizationDrawer open={normOpen} onOpenChange={setNormOpen} />
    </>
  )
}
