// StudyBrowser -- the header picker for the Study page. Replaces the
// documents-only dropdown with one popover that browses BOTH collections and
// standalone documents in two clearly separated, labelled sections, so you can
// jump to either from any state (a doc being open no longer traps you).

import { useEffect, useMemo, useRef, useState } from "react"
import {
  BookOpen,
  Check,
  ChevronDown,
  CornerDownRight,
  Home,
  Layers,
  Search,
  StickyNote,
} from "lucide-react"

import type { DocListItem } from "./types"

export interface CollectionNode {
  id: string
  name: string
  color?: string
  document_count?: number
  note_count?: number
  children?: CollectionNode[]
}

interface StudyBrowserProps {
  docs: DocListItem[]
  collections: CollectionNode[]
  activeDocId: string | null
  activeCollectionId: string | null
  onSelectDoc: (id: string) => void
  onSelectCollection: (id: string) => void
  onClear: () => void
}

interface FlatCollection extends CollectionNode {
  _depth: number
  _parentName: string | null
}

function flattenCollections(
  items: CollectionNode[],
  depth = 0,
  parentName: string | null = null,
): FlatCollection[] {
  const out: FlatCollection[] = []
  for (const item of items) {
    out.push({ ...item, _depth: depth, _parentName: parentName })
    if (item.children?.length) {
      out.push(...flattenCollections(item.children, depth + 1, item.name))
    }
  }
  return out
}

export function StudyBrowser({
  docs,
  collections,
  activeDocId,
  activeCollectionId,
  onSelectDoc,
  onSelectCollection,
  onClear,
}: StudyBrowserProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false)
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  const flatCollections = useMemo(() => flattenCollections(collections), [collections])

  const q = query.trim().toLowerCase()
  const filteredCollections = q
    ? flatCollections.filter((c) => c.name.toLowerCase().includes(q))
    : flatCollections
  const filteredDocs = q
    ? docs.filter((d) => d.title.toLowerCase().includes(q))
    : docs

  const activeCollection = flatCollections.find((c) => c.id === activeCollectionId)
  const activeDoc = docs.find((d) => d.id === activeDocId)

  // Trigger label + icon reflect what's currently selected.
  const triggerIcon = activeCollection ? (
    <Layers size={16} className="text-primary" />
  ) : activeDoc ? (
    <BookOpen size={16} className="text-blue-500" />
  ) : (
    <Search size={16} className="text-muted-foreground" />
  )
  const triggerLabel =
    activeCollection?.name ?? activeDoc?.title ?? "Browse collections & documents"

  const choose = (fn: () => void) => {
    fn()
    setOpen(false)
    setQuery("")
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 min-w-[240px] max-w-[360px] items-center gap-2 rounded-full border border-border bg-card px-4 text-xs font-semibold text-foreground transition-all hover:border-primary/50 focus:border-primary focus:outline-none"
      >
        {triggerIcon}
        <span className="truncate">{triggerLabel}</span>
        <ChevronDown
          size={14}
          className={`ml-auto shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute left-0 top-11 z-50 w-[380px] overflow-hidden rounded-xl border border-border bg-popover shadow-xl">
          {/* Search */}
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search size={14} className="text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search collections and documents..."
              className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </div>

          <div className="max-h-[420px] overflow-y-auto py-1">
            {/* Home / clear */}
            <button
              onClick={() => choose(onClear)}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
            >
              <Home size={15} className="text-muted-foreground" />
              <span className="text-foreground">Study home</span>
              {!activeCollectionId && !activeDocId && (
                <Check size={14} className="ml-auto text-primary" />
              )}
            </button>

            {/* Collections section */}
            <SectionLabel icon={Layers} label="Collections" count={filteredCollections.length} />
            {filteredCollections.length === 0 ? (
              <EmptyRow text={q ? "No matching collections" : "No collections yet"} />
            ) : (
              filteredCollections.map((c) => (
                <button
                  key={c.id}
                  onClick={() => choose(() => onSelectCollection(c.id))}
                  className={`group flex w-full items-center gap-2.5 py-2 pr-3 text-left text-sm transition-colors hover:bg-accent ${
                    c.id === activeCollectionId ? "bg-primary/5" : ""
                  }`}
                  style={{ paddingLeft: 12 + c._depth * 16 }}
                >
                  {c._depth > 0 && (
                    <CornerDownRight size={12} className="shrink-0 text-muted-foreground/50" />
                  )}
                  <Layers size={15} className="shrink-0 text-primary" />
                  <span className="truncate text-foreground">{c.name}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
                    {(c.document_count ?? 0) > 0 && (
                      <span className="flex items-center gap-0.5">
                        <BookOpen size={11} className="text-blue-500/70" />
                        {c.document_count}
                      </span>
                    )}
                    {(c.note_count ?? 0) > 0 && (
                      <span className="flex items-center gap-0.5">
                        <StickyNote size={11} className="text-amber-500/70" />
                        {c.note_count}
                      </span>
                    )}
                    {c.id === activeCollectionId && <Check size={14} className="text-primary" />}
                  </span>
                </button>
              ))
            )}

            {/* Documents section */}
            <SectionLabel icon={BookOpen} label="Documents" count={filteredDocs.length} />
            {filteredDocs.length === 0 ? (
              <EmptyRow text={q ? "No matching documents" : "No documents yet"} />
            ) : (
              filteredDocs.map((d) => (
                <button
                  key={d.id}
                  onClick={() => choose(() => onSelectDoc(d.id))}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
                    d.id === activeDocId ? "bg-primary/5" : ""
                  }`}
                >
                  <BookOpen size={15} className="shrink-0 text-blue-500" />
                  <span className="truncate text-foreground">{d.title}</span>
                  {d.id === activeDocId && (
                    <Check size={14} className="ml-auto shrink-0 text-primary" />
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SectionLabel({
  icon: Icon,
  label,
  count,
}: {
  icon: typeof Layers
  label: string
  count: number
}) {
  return (
    <div className="mt-1 flex items-center gap-1.5 px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      <Icon size={11} />
      {label}
      <span className="text-muted-foreground/60">({count})</span>
    </div>
  )
}

function EmptyRow({ text }: { text: string }) {
  return <div className="px-3 py-2 text-xs italic text-muted-foreground/70">{text}</div>
}
