// Floating popover that appears next to a clicked node. Shows the
// label + type pill, the mention count or learning-path breadcrumb,
// the source-diagram thumbnail when applicable, and a
// "Find in document" jump.

import { X } from "lucide-react"

import { API_BASE } from "@/lib/config"
import type { EntityType } from "@/lib/vizUtils"

import { DEFAULT_COLOR, TYPE_COLORS } from "./constants"
import type { SelectedNodeInfo } from "./types"

interface NodePopoverProps {
  node: SelectedNodeInfo
  viewMode: string
  lpBreadcrumb: string[]
  activeDocumentId: string | null
  onClose: () => void
  onNavigate: (path: string) => void
}

export function NodePopover({
  node,
  viewMode,
  lpBreadcrumb,
  activeDocumentId,
  onClose,
  onNavigate,
}: NodePopoverProps) {
  return (
    <div
      className="fixed z-50 rounded-2xl border border-border bg-background/95 backdrop-blur-sm shadow-xl p-4 min-w-[200px] max-w-[280px]"
      style={{ left: node.screenX + 12, top: node.screenY - 70 }}
    >
      <button
        onClick={onClose}
        className="absolute top-2 right-2 rounded p-0.5 text-muted-foreground/40 hover:text-foreground transition-colors"
      >
        <X size={12} />
      </button>
      <div className="flex items-center gap-2 mb-2">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
          style={{
            backgroundColor: TYPE_COLORS[node.type as EntityType] ?? DEFAULT_COLOR,
          }}
        />
        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wide">
          {node.type.replace(/_/g, " ")}
        </span>
      </div>
      <p className="text-sm font-bold text-foreground mb-1">{node.label}</p>
      {viewMode === "learning_path" && lpBreadcrumb.length > 1 ? (
        <div className="mb-3">
          <p className="text-[10px] font-semibold text-muted-foreground mb-1 uppercase">
            Prerequisites
          </p>
          <p className="text-xs text-foreground leading-relaxed">
            {lpBreadcrumb.join(" -> ")}
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground mb-3">
          {node.frequency} {node.frequency === 1 ? "mention" : "mentions"}
        </p>
      )}
      {/* Image thumbnail for diagram-derived nodes */}
      {node.source_image_id && (
        <div className="mb-3">
          <img
            src={`${API_BASE}/images/${node.source_image_id}/raw`}
            alt="Source diagram"
            className="w-full rounded-lg border border-border object-contain max-h-40"
            onError={(e) => {
              ;(e.target as HTMLImageElement).style.display = "none"
            }}
          />
        </div>
      )}
      <button
        onClick={() => {
          const docId = activeDocumentId
          const entityLabel = node.label
          onClose()
          if (docId) {
            onNavigate(
              `/?doc=${encodeURIComponent(docId)}&search=${encodeURIComponent(entityLabel)}`,
            )
          } else {
            onNavigate(`/?search=${encodeURIComponent(entityLabel)}`)
          }
        }}
        className="w-full rounded-lg bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 transition-colors text-center"
      >
        Find in document
      </button>
    </div>
  )
}
