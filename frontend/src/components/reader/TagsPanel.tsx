import { Check, Pencil, Search, X } from "lucide-react"
import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { apiGet, apiPatch } from "@/lib/apiClient"
import { cn } from "@/lib/utils"

interface DocTagsResponse {
  id: string
  tags: string[]
}

interface TagsPanelProps {
  documentId: string
}

const DOC_SEARCH_EVENT = "luminary:doc-search"

function dispatchDocSearch(query: string) {
  if (!query) return
  window.dispatchEvent(new CustomEvent(DOC_SEARCH_EVENT, { detail: { query } }))
}

function unslug(slug: string): string {
  // Best-effort surface form for in-doc search: 'data-lakehouse' -> 'data lakehouse'.
  // The slug lost casing during normalization; FTS5 is case-insensitive so
  // this works for most documents. Hierarchical tags ('science/biology')
  // search on the leaf to maximise match likelihood.
  const leaf = slug.split("/").pop() ?? slug
  return leaf.replace(/-/g, " ")
}

export function TagsPanel({ documentId }: TagsPanelProps) {
  const qc = useQueryClient()
  const [filter, setFilter] = useState("")
  const [adding, setAdding] = useState(false)
  const [newTag, setNewTag] = useState("")
  // Two-step delete: first × click arms the chip, second confirms. Clicking
  // any other chip or pressing Esc resets. We hold one tag at a time --
  // batching deletes wasn't asked for.
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["doc-detail-tags", documentId],
    queryFn: () => apiGet<DocTagsResponse>(`/documents/${documentId}`),
    staleTime: 30_000,
  })

  const tags = useMemo(() => data?.tags ?? [], [data])
  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return tags
    return tags.filter((t) => t.includes(q))
  }, [tags, filter])

  const patchTags = useMutation({
    mutationFn: (next: string[]) =>
      apiPatch<DocTagsResponse>(`/documents/${documentId}/tags`, { tags: next }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["doc-detail-tags", documentId] })
      void qc.invalidateQueries({ queryKey: ["documents"] })
      void qc.invalidateQueries({ queryKey: ["tags"] })
    },
  })

  function addTag() {
    const t = newTag.trim().toLowerCase()
    if (!t) {
      setAdding(false)
      return
    }
    if (!tags.includes(t)) {
      patchTags.mutate([...tags, t])
    }
    setNewTag("")
    setAdding(false)
  }

  function requestRemove(tag: string) {
    setPendingDelete(tag)
  }

  function confirmRemove(tag: string) {
    patchTags.mutate(tags.filter((t) => t !== tag))
    setPendingDelete(null)
  }

  function cancelRemove() {
    setPendingDelete(null)
  }

  // Esc anywhere in the panel cancels a pending delete.
  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape" && pendingDelete) {
      cancelRemove()
    }
  }

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">Loading tags…</p>
    )
  }
  if (isError) {
    return (
      <div className="flex flex-col gap-2 text-sm">
        <span className="text-amber-700">Could not load tags.</span>
        <button onClick={() => void refetch()} className="self-start text-xs text-primary hover:underline">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-3" onKeyDown={onKeyDown} tabIndex={-1}>
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={`Filter ${tags.length} tag${tags.length === 1 ? "" : "s"}…`}
            className="w-full rounded-md border border-border bg-background py-1 pl-7 pr-2 text-xs focus:border-primary focus:outline-none"
          />
        </div>
        {!adding ? (
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            title="Add a manual tag"
          >
            <Pencil size={11} />
            Add
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <input
              autoFocus
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addTag()
                if (e.key === "Escape") {
                  setAdding(false)
                  setNewTag("")
                }
              }}
              onBlur={addTag}
              placeholder="new tag…"
              className="h-6 w-32 rounded border border-primary bg-background px-1.5 text-xs focus:outline-none"
            />
            <button onClick={addTag} className="text-primary">
              <Check size={12} />
            </button>
          </div>
        )}
      </div>

      {tags.length === 0 ? (
        <p className="text-xs text-muted-foreground">No tags yet. Tags get added during ingestion; use Add to set one manually.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5 overflow-y-auto">
          {visible.map((tag) => {
            const armed = pendingDelete === tag
            return (
              <span
                key={tag}
                className={cn(
                  "group flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors",
                  armed
                    ? "border-destructive/50 bg-destructive/10 text-destructive"
                    : "border-border bg-accent/40 text-foreground/80 hover:border-primary/50 hover:bg-primary/10",
                )}
              >
                {armed ? (
                  <>
                    <span className="font-medium">Remove “{tag}”?</span>
                    <button
                      onClick={() => confirmRemove(tag)}
                      className="rounded px-1 text-destructive hover:bg-destructive/20"
                      title="Confirm remove"
                    >
                      <Check size={11} />
                    </button>
                    <button
                      onClick={cancelRemove}
                      className="rounded px-1 text-muted-foreground hover:bg-muted"
                      title="Cancel"
                    >
                      <X size={11} />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => dispatchDocSearch(unslug(tag))}
                      className="text-left"
                      title={`Find “${unslug(tag)}” in this document`}
                    >
                      {tag}
                    </button>
                    <button
                      onClick={() => requestRemove(tag)}
                      className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                      title="Remove tag"
                    >
                      <X size={10} />
                    </button>
                  </>
                )}
              </span>
            )
          })}
          {visible.length === 0 && filter && (
            <p className="text-xs text-muted-foreground">No tags match &ldquo;{filter}&rdquo;.</p>
          )}
        </div>
      )}
    </div>
  )
}
