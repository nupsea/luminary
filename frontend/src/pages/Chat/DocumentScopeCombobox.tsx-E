// Inline document-scope combobox shown in the Chat header.

import { BookOpen, ChevronDown, Globe, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { buildScopeComboboxLabel } from "@/lib/chatSettingsUtils"

import type { DocListItem } from "./types"

interface DocumentScopeComboboxProps {
  docList: DocListItem[] | undefined
  selectedDocId: string | null
  onSelect: (docId: string | null) => void
}

export function DocumentScopeCombobox({ docList, selectedDocId, onSelect }: DocumentScopeComboboxProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  const selectedTitle = docList?.find((d) => d.id === selectedDocId)?.title ?? null
  const label = buildScopeComboboxLabel(selectedTitle)

  const filtered = (docList ?? []).filter((d) =>
    d.title.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => { setOpen((prev) => !prev); setSearch("") }}
        className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-accent transition-colors max-w-[240px]"
        title={selectedTitle ?? "All documents"}
      >
        {selectedDocId ? (
          <>
            <BookOpen size={13} className="shrink-0 text-muted-foreground" />
            <span className="truncate">{label}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onSelect(null) }}
              className="ml-0.5 shrink-0 rounded p-0.5 hover:bg-accent"
              aria-label="Clear document selection"
            >
              <X size={12} />
            </button>
          </>
        ) : (
          <>
            <Globe size={13} className="shrink-0 text-muted-foreground" />
            <span>{label}</span>
            <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
          </>
        )}
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-64 rounded-md border border-border bg-background shadow-lg">
          <div className="border-b border-border px-2 py-1.5">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search documents..."
              className="w-full bg-transparent text-xs text-foreground placeholder:text-muted-foreground outline-none"
              autoFocus
            />
          </div>
          <div className="max-h-48 overflow-auto py-1">
            {docList === undefined ? (
              <div className="px-3 py-2">
                <Skeleton className="h-4 w-full" />
              </div>
            ) : filtered.length === 0 ? (
              <p className="px-3 py-2 text-xs text-muted-foreground">No documents yet</p>
            ) : (
              filtered.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => { onSelect(doc.id); setOpen(false) }}
                  className={`w-full px-3 py-1.5 text-left text-xs hover:bg-accent transition-colors truncate ${doc.id === selectedDocId ? "bg-accent/50 font-medium" : "text-foreground"
                    }`}
                >
                  {doc.title}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
