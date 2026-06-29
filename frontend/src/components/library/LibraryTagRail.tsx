import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Search } from "lucide-react"
import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"

import { Skeleton } from "@/components/ui/skeleton"
import { apiGet, apiPost } from "@/lib/apiClient"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/store"

interface TagRow {
  id: string
  display_name: string
  parent_tag: string | null
  usage_count: number
  scoped_count: number
}

interface CrossContentCounts {
  document_count: number
  note_count: number
}

interface LibraryTagRailProps {
  activeTag: string | null
  onSelect: (tag: string | null) => void
  /** Initial chip cap before "show all" expands. */
  collapsedLimit?: number
}

// Fetch a generous slice so the in-rail filter has material to work with.
// 200 was chosen to comfortably cover all doc-scoped tags on a typical
// corpus while staying well below the backend's 200 query-param cap.
const DEFAULT_FETCH_LIMIT = 200

export function LibraryTagRail({
  activeTag,
  onSelect,
  collapsedLimit = 6,
}: LibraryTagRailProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const setActiveTagInStore = useAppStore((s) => s.setActiveTag)
  const [retagDone, setRetagDone] = useState(false)
  const [filter, setFilter] = useState("")
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["tags", "scope:document", DEFAULT_FETCH_LIMIT],
    queryFn: () =>
      apiGet<TagRow[]>("/tags", { scope: "document", limit: DEFAULT_FETCH_LIMIT }),
    staleTime: 30_000,
  })

  // Spill-over: only fetch the cross-content split when a tag is actually
  // active. The Library rail already shows the doc-scoped count per chip;
  // this extra call surfaces the *note*-scoped count for the active tag so
  // the user can hop across without going through Cmd+K (plan 2E.4).
  const { data: crossCounts } = useQuery({
    queryKey: ["tag-cross-content-counts", activeTag],
    queryFn: () =>
      apiGet<CrossContentCounts>(`/tags/${encodeURIComponent(activeTag!)}/cross-content-counts`),
    enabled: !!activeTag,
    staleTime: 60_000,
  })

  const retagAll = useMutation({
    mutationFn: () => apiPost<{ queued: number }>("/documents/retag-all", {}),
    onSuccess: (res) => {
      setRetagDone(true)
      toast.success(`Queued ${res.queued} document${res.queued === 1 ? "" : "s"} for auto-tagging. Tags appear as background jobs finish.`)
      // Poll the tags endpoint a few times so chips show up as work completes.
      const tick = (n: number) => {
        if (n <= 0) return
        setTimeout(() => {
          void queryClient.invalidateQueries({ queryKey: ["tags"] })
          void queryClient.invalidateQueries({ queryKey: ["documents"] })
          tick(n - 1)
        }, 3000)
      }
      tick(5)
    },
    onError: () => toast.error("Could not queue auto-tag job."),
  })

  const allTags = data ?? []
  // Filter narrows the chip list as the user types. When the filter is on,
  // the collapsed/expanded split is skipped -- the user is doing a directed
  // search, not a casual browse, so we show all matches at once.
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return allTags
    return allTags.filter((t) => t.id.includes(q))
  }, [allTags, filter])
  const isFiltering = filter.trim().length > 0
  const overflow = !isFiltering && filtered.length > collapsedLimit
  const visible = isFiltering ? filtered : filtered.slice(0, collapsedLimit)
  const hidden = isFiltering ? [] : filtered.slice(collapsedLimit)
  const tags = filtered

  return (
    <aside className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center justify-between">
        <h3 className="lum-eyebrow">Tags</h3>
        {activeTag && (
          <button
            onClick={() => onSelect(null)}
            className="text-[11px] text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
          >
            Clear
          </button>
        )}
      </div>

      {!isLoading && !isError && allTags.length > collapsedLimit && (
        <div className="relative">
          <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={`Search ${allTags.length} tags…`}
            className="w-full rounded-md border border-border bg-background py-1 pl-6 pr-2 text-[11px] focus:border-primary focus:outline-none"
          />
        </div>
      )}

      {isLoading && (
        <div className="flex flex-wrap gap-1.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-5 w-14 rounded-full" />
          ))}
        </div>
      )}

      {isError && (
        <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          <span>Could not load tags</span>
          <button
            onClick={() => void refetch()}
            className="self-start rounded border border-amber-300 bg-white px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-50 dark:border-amber-800 dark:bg-transparent dark:text-amber-300 dark:hover:bg-amber-900/40"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && allTags.length === 0 && (
        <div className="flex flex-col gap-2 py-1">
          <p className="text-xs text-muted-foreground">No tags yet</p>
          <button
            onClick={() => retagAll.mutate()}
            disabled={retagAll.isPending || retagDone}
            className="self-start rounded-md border border-border bg-background px-2 py-1 text-[11px] text-foreground/80 hover:bg-accent disabled:opacity-60"
            title="Run auto-tagger across every completed document. Uses graph entities (no LLM calls for the entity path)."
          >
            {retagAll.isPending
              ? "Queuing…"
              : retagDone
                ? "Job queued — tags appear shortly"
                : "Auto-tag all documents"}
          </button>
        </div>
      )}

      {!isLoading && !isError && allTags.length > 0 && tags.length === 0 && isFiltering && (
        <p className="py-1 text-[11px] text-muted-foreground">
          No tags match &ldquo;{filter}&rdquo;.
        </p>
      )}

      {!isLoading && !isError && tags.length > 0 && (
        <details className="flex flex-col gap-1" open={!overflow}>
          <summary className="flex flex-wrap items-center gap-1.5 cursor-pointer list-none">
            {visible.map((t) => (
              <TagChip
                key={t.id}
                tag={t}
                active={activeTag === t.id}
                onSelect={onSelect}
              />
            ))}
            {overflow && (
              <span className="text-[11px] text-muted-foreground hover:text-foreground underline-offset-2 hover:underline">
                show all {tags.length} →
              </span>
            )}
          </summary>
          {overflow && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              {hidden.map((t) => (
                <TagChip
                  key={t.id}
                  tag={t}
                  active={activeTag === t.id}
                  onSelect={onSelect}
                />
              ))}
            </div>
          )}
        </details>
      )}

      {activeTag && crossCounts && crossCounts.note_count > 0 && (
        <button
          type="button"
          onClick={() => {
            // Set the store tag so Notes' tree highlights it on arrival
            // and the notes list pre-filters; nav follows.
            setActiveTagInStore(activeTag)
            navigate(`/notes?tag=${encodeURIComponent(activeTag)}`, { state: { from: "/library" } })
          }}
          className="mt-1 flex items-center gap-1 self-start rounded-md border border-dashed border-border bg-background px-2 py-1 text-[11px] text-muted-foreground hover:border-primary/40 hover:text-foreground"
          title={`Open Notes filtered to #${activeTag}`}
        >
          <span>
            Also in {crossCounts.note_count} note{crossCounts.note_count === 1 ? "" : "s"}
          </span>
          <ArrowRight size={11} />
        </button>
      )}
    </aside>
  )
}

function TagChip({
  tag,
  active,
  onSelect,
}: {
  tag: TagRow
  active: boolean
  onSelect: (tag: string | null) => void
}) {
  return (
    <button
      onClick={() => onSelect(active ? null : tag.id)}
      className={cn(
        "flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors",
        active
          ? "border-primary bg-primary/15 text-primary"
          : "border-border bg-background text-foreground/80 hover:bg-accent",
      )}
      title={`${tag.scoped_count} document${tag.scoped_count === 1 ? "" : "s"} (${tag.usage_count} total)`}
    >
      <span className="truncate max-w-[12rem]">{tag.id}</span>
      <span
        className={cn(
          "rounded-full px-1 text-[10px]",
          active ? "text-primary/80" : "text-muted-foreground",
        )}
      >
        {tag.scoped_count}
      </span>
    </button>
  )
}
