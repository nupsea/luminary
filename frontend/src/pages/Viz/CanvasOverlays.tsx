// Full-canvas absolute-positioned overlays (loading skeletons, error
// states, empty states) for the Viz page. Mutually exclusive in
// practice: the parent decides which flag is true and renders this
// once. Keeping the states in one component avoids scattering
// the same layout primitives across the page.

import { Filter, Network } from "lucide-react"

import { InstallComponentButton } from "@/components/setup/InstallComponentButton"
import { Skeleton } from "@/components/ui/skeleton"
import type { GraphEmptyReason } from "@/lib/vizUtils"

// No in-app rebuild exists for documents ingested without the entity model, so the
// copy says so rather than implying an install fills the graph.
function emptyCopy(reason: GraphEmptyReason, scope: "document" | "all") {
  const where = scope === "document" ? "this document" : "your documents"
  switch (reason) {
    case "no_documents":
      return {
        title: "No knowledge graph yet",
        body: "Add a document to the library. The people, places and ideas in it will appear here.",
      }
    case "model_missing":
      return {
        title: "Concept extraction is not installed",
        body: `Without it, no entities were extracted from ${where}. Documents you add after installing it get a graph; documents already in the library are not rebuilt.`,
      }
    case "extraction_off":
      return {
        title: "Concept extraction is turned off",
        body: "GLINER_ENABLED is false in this install's settings, so documents are added without a knowledge graph.",
      }
    case "no_entities":
      return {
        title: "No entities found",
        body: `Nothing was extracted from ${where}. A document added before concept extraction was installed has no graph.`,
      }
  }
}

interface CanvasOverlaysProps {
  // Knowledge graph states
  kgShowLoading: boolean
  kgShowError: boolean
  showEmpty: boolean
  emptyReason: GraphEmptyReason
  emptyScope: "document" | "all"
  showAllHidden: boolean
  entityNodeCount: number
  onKgRetry: () => void
}

export function CanvasOverlays(props: CanvasOverlaysProps) {
  const {
    kgShowLoading,
    kgShowError,
    showEmpty,
    emptyReason,
    emptyScope,
    showAllHidden,
    entityNodeCount,
    onKgRetry,
  } = props

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
    const { title, body } = emptyCopy(emptyReason, emptyScope)
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-center p-6">
        <div className="rounded-2xl bg-muted/30 p-6">
          <Network size={48} className="text-muted-foreground/30" />
        </div>
        <p className="text-lg font-semibold text-foreground">{title}</p>
        <p className="text-sm text-muted-foreground max-w-sm">{body}</p>
        {emptyReason === "model_missing" && (
          <InstallComponentButton componentId="ner" className="items-center" />
        )}
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
