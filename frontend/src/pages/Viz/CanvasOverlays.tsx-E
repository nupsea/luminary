// Full-canvas absolute-positioned overlays (loading skeletons, error
// states, empty states) for the Viz page. Mutually exclusive in
// practice: the parent decides which flag is true and renders this
// once. Keeping all eight states in one component avoids scattering
// the same layout primitives across the page.

import { Filter, Network, Zap } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

interface CanvasOverlaysProps {
  // Learning path states
  lpNoInput: boolean
  lpShowLoading: boolean
  lpShowError: boolean
  lpShowEmpty: boolean
  learningPathStart: string
  onLpRetry: () => void
  // Knowledge graph states
  kgShowLoading: boolean
  kgShowError: boolean
  showEmpty: boolean
  showAllHidden: boolean
  entityNodeCount: number
  onKgRetry: () => void
}

export function CanvasOverlays(props: CanvasOverlaysProps) {
  const {
    lpNoInput,
    lpShowLoading,
    lpShowError,
    lpShowEmpty,
    learningPathStart,
    onLpRetry,
    kgShowLoading,
    kgShowError,
    showEmpty,
    showAllHidden,
    entityNodeCount,
    onKgRetry,
  } = props

  if (lpNoInput) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
        <div className="rounded-2xl bg-muted/30 p-6">
          <Zap size={48} className="text-muted-foreground/30" />
        </div>
        <p className="text-lg font-semibold text-foreground">Enter a start entity</p>
        <p className="text-sm text-muted-foreground max-w-xs">
          Type a concept name in the sidebar and press Enter to view its prerequisite chain.
        </p>
      </div>
    )
  }

  if (lpShowLoading) {
    return (
      <div className="absolute inset-0 flex flex-col gap-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="flex-1 w-full rounded-lg" />
      </div>
    )
  }

  if (lpShowError) {
    return (
      <div className="absolute inset-0 flex items-center justify-center p-6">
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-red-200 bg-red-50 px-8 py-6 text-sm text-red-700">
          <p className="font-semibold">Failed to load learning path</p>
          <button
            onClick={onLpRetry}
            className="rounded-lg border border-red-300 bg-white px-4 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (lpShowEmpty) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
        <div className="rounded-2xl bg-muted/30 p-6">
          <Network size={48} className="text-muted-foreground/30" />
        </div>
        <p className="text-lg font-semibold text-foreground">
          No prerequisite path found for &ldquo;{learningPathStart}&rdquo;
        </p>
        <p className="text-sm text-muted-foreground max-w-xs">
          This entity has no PREREQUISITE_OF edges in this document. Try a different concept.
        </p>
      </div>
    )
  }

  if (kgShowLoading) {
    return (
      <div className="absolute inset-0 flex flex-col gap-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="flex-1 w-full rounded-lg" />
      </div>
    )
  }

  if (kgShowError) {
    return (
      <div className="absolute inset-0 flex items-center justify-center p-6">
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-red-200 bg-red-50 px-8 py-6 text-sm text-red-700">
          <p className="font-semibold">Failed to load knowledge graph</p>
          <button
            onClick={onKgRetry}
            className="rounded-lg border border-red-300 bg-white px-4 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (showEmpty) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
        <div className="rounded-2xl bg-muted/30 p-6">
          <Network size={48} className="text-muted-foreground/30" />
        </div>
        <p className="text-lg font-semibold text-foreground">No knowledge graph yet</p>
        <p className="text-sm text-muted-foreground max-w-xs">
          Ingest a document first -- entities and relationships will appear here.
        </p>
      </div>
    )
  }

  if (showAllHidden) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
        <div className="rounded-2xl bg-muted/30 p-6">
          <Filter size={48} className="text-muted-foreground/30" />
        </div>
        <p className="text-lg font-semibold text-foreground">All entity types are hidden</p>
        <p className="text-sm text-muted-foreground max-w-xs">
          {entityNodeCount} {entityNodeCount === 1 ? "entity" : "entities"} found. Enable at
          least one entity type in the sidebar.
        </p>
      </div>
    )
  }

  return null
}
