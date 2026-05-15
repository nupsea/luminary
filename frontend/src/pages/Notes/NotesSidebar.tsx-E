// Left-hand sidebar of the Notes page: All-Notes / Reading-Journal
// shortcuts, the collection tree, the tag tree, and the cluster
// suggestions block (with its OrganizationPlanDialog). All state
// lives in the parent; this component is presentation + dispatch.

import { useQueryClient } from "@tanstack/react-query"
import { BookOpen, Loader2, Plus, Wand2 } from "lucide-react"
import { toast } from "sonner"

import { CollectionTree } from "@/components/CollectionTree"
import { TagTree } from "@/components/TagTree"
import {
  OrganizationPlanDialog,
  type NamingViolation,
} from "@/components/OrganizationPlanDialog"

import type { ClusterSuggestion, GroupsData } from "./types"

type FilterState =
  | { type: "all" }
  | { type: "journal" }
  | { type: "group"; name: string }
  | { type: "tag"; name: string }

interface NotesSidebarProps {
  filter: FilterState
  onSetFilter: (f: FilterState) => void
  activeCollectionId: string | null
  onSetActiveCollectionId: (id: string | null) => void
  activeTag: string | null
  onSetActiveTag: (tag: string | null) => void
  groups: GroupsData | undefined
  fallbackNoteCount: number
  onShowCreateCollection: () => void
  // Cluster suggestions
  clusterSuggestions: ClusterSuggestion[]
  isClusterQueued: boolean
  clusterSuggestionsLoading: boolean
  clusterSuggestionsError: boolean
  onAutoOrganize: () => void
  onRefetchClusterSuggestions: () => void
  // Organization plan dialog
  showOrgPlan: boolean
  onSetShowOrgPlan: (open: boolean) => void
  namingViolations: NamingViolation[]
}

export function NotesSidebar({
  filter,
  onSetFilter,
  activeCollectionId,
  onSetActiveCollectionId,
  activeTag,
  onSetActiveTag,
  groups,
  fallbackNoteCount,
  onShowCreateCollection,
  clusterSuggestions,
  isClusterQueued,
  clusterSuggestionsLoading,
  clusterSuggestionsError,
  onAutoOrganize,
  onRefetchClusterSuggestions,
  showOrgPlan,
  onSetShowOrgPlan,
  namingViolations,
}: NotesSidebarProps) {
  const qc = useQueryClient()

  return (
    <div className="flex w-[280px] shrink-0 flex-col gap-1 overflow-auto border-r border-border p-4">
      <button
        onClick={() => {
          onSetFilter({ type: "all" })
          onSetActiveCollectionId(null)
          onSetActiveTag(null)
        }}
        className={`flex items-center gap-2 rounded px-3 py-2 text-sm text-left transition-colors ${
          filter.type === "all" && !activeCollectionId && !activeTag
            ? "bg-accent font-medium text-foreground"
            : "text-muted-foreground hover:bg-accent/60"
        }`}
      >
        All Notes
        <span className="ml-auto text-xs">{groups?.total_notes ?? fallbackNoteCount}</span>
      </button>

      <button
        onClick={() => {
          onSetFilter({ type: "journal" })
          onSetActiveCollectionId(null)
          onSetActiveTag(null)
        }}
        className={`flex items-center gap-2 rounded px-3 py-2 text-sm text-left transition-colors ${
          filter.type === "journal"
            ? "bg-accent font-medium text-foreground"
            : "text-muted-foreground hover:bg-accent/60"
        }`}
      >
        <BookOpen size={13} />
        Reading Journal
      </button>

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between px-1">
          <p className="px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Collections
          </p>
          <button
            onClick={onShowCreateCollection}
            className="rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-accent"
            title="New collection"
          >
            <Plus size={12} />
          </button>
        </div>
        <CollectionTree />
        <button
          onClick={onShowCreateCollection}
          className="mt-1 flex w-full items-center gap-1 rounded px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground"
        >
          <Plus size={11} />
          New Collection
        </button>
      </div>

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between px-1">
          <p className="px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Tags
          </p>
        </div>
        <TagTree />
      </div>

      {(clusterSuggestions.length > 0 || isClusterQueued) && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between px-1">
            <p className="px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Suggested Collections
            </p>
            <button
              onClick={onAutoOrganize}
              disabled={isClusterQueued}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-50"
              title="Auto-organize notes into collections"
            >
              {isClusterQueued ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Wand2 size={12} />
              )}
            </button>
          </div>
          {clusterSuggestionsLoading && (
            <div className="space-y-1.5 px-1">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-12 animate-pulse rounded bg-accent/40" />
              ))}
            </div>
          )}
          {clusterSuggestionsError && (
            <p className="px-3 text-xs text-amber-500">
              Could not load suggestions.{" "}
              <button onClick={onRefetchClusterSuggestions} className="underline">
                Retry
              </button>
            </p>
          )}
          {clusterSuggestions.length > 0 && !clusterSuggestionsLoading && (
            <button
              onClick={() => onSetShowOrgPlan(true)}
              className="w-full rounded border border-border p-2 text-xs text-left hover:bg-accent/40"
            >
              <span className="font-medium">
                {clusterSuggestions.length} group
                {clusterSuggestions.length !== 1 ? "s" : ""} found
              </span>
              <span className="text-muted-foreground"> -- click to review plan</span>
            </button>
          )}
        </div>
      )}

      {clusterSuggestions.length === 0 && !isClusterQueued && (
        <div className="mt-3">
          <button
            onClick={onAutoOrganize}
            className="flex w-full items-center gap-1 rounded px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            title="Auto-organize notes into suggested collections"
          >
            <Wand2 size={11} />
            Auto-organize
          </button>
        </div>
      )}

      <OrganizationPlanDialog
        open={showOrgPlan}
        onOpenChange={onSetShowOrgPlan}
        suggestions={clusterSuggestions}
        namingViolations={namingViolations}
        onApplied={() => {
          void qc.invalidateQueries({ queryKey: ["clusterSuggestions"] })
          void qc.invalidateQueries({ queryKey: ["collections"] })
          void qc.invalidateQueries({ queryKey: ["collections-tree"] })
          void qc.invalidateQueries({ queryKey: ["tags"] })
          void qc.invalidateQueries({ queryKey: ["notes"] })
          void qc.invalidateQueries({ queryKey: ["notes-groups"] })
          toast.success("Organization plan applied")
        }}
        onNamingFixesApplied={(result) => {
          const parts: string[] = []
          if (result.tags_renamed > 0)
            parts.push(`Renamed ${result.tags_renamed} tag${result.tags_renamed !== 1 ? "s" : ""}`)
          if (result.tags_merged > 0)
            parts.push(`Merged ${result.tags_merged} tag${result.tags_merged !== 1 ? "s" : ""}`)
          if (result.collections_renamed > 0)
            parts.push(
              `Renamed ${result.collections_renamed} collection${result.collections_renamed !== 1 ? "s" : ""}`,
            )
          if (parts.length > 0) toast.success(parts.join(". "))
        }}
        onDismissed={() => {
          void qc.invalidateQueries({ queryKey: ["clusterSuggestions"] })
        }}
      />
    </div>
  )
}
