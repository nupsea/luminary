// Left-hand sidebar of the Viz page. Hidden when viewMode === "tags".
//
// Contains five sections:
//   1. Library context: doc filter + per-doc quick-select list
//   2. Notes in Context (when the notes layer is on)
//   3. Learning path start-entity input (only in learning_path mode)
//   4. Layers toggles (diagrams, prerequisites, cross-book, notes,
//      retention)
//   5. Needs Attention list (only when retention overlay is on)
//   6. Entity type filter + cluster view toggle
//
// All state lives in the parent (Viz.tsx); this component is a pure
// presentation surface that fires callbacks back. The props bag is
// large because the surface itself is large -- keep it that way
// rather than tunnelling state through context.

import type Graph from "graphology"
import { AlertTriangle, BookOpen, Eye, FileText, Filter, Library, Network, Search, StickyNote, X } from "lucide-react"

import type { ALL_ENTITY_TYPES } from "@/lib/vizUtils"
import { NOTE_NODE_COLOR } from "@/lib/noteGraphUtils"

import {
  BLIND_SPOT_COLOR,
  PREREQ_EDGE_COLOR,
  SAME_CONCEPT_COLOR,
  TYPE_COLORS,
} from "./constants"
import type { DocListItem, MasteryConceptsResponse } from "./types"
import { masteryColor } from "./utils"

type EntityType = (typeof ALL_ENTITY_TYPES)[number]

interface VizSidebarProps {
  viewMode: string
  // Library
  docPickerSearch: string
  onDocPickerSearchChange: (v: string) => void
  onClearGlobalSearch: () => void
  activeDocumentId: string | null
  onDocSelect: (docId: string | null) => void
  filteredDocList: DocListItem[]
  // Notes context
  showNotes: boolean
  filteredGraph: Graph | null
  selectedNoteId: string | null
  onSelectNoteId: (id: string | null) => void
  onClearSelectedNode: () => void
  // Learning path
  lpInputDraft: string
  onLpInputDraftChange: (v: string) => void
  onSetLearningPathStart: (entity: string) => void
  // Layers
  showDiagramNodes: boolean
  setShowDiagramNodes: (fn: (v: boolean) => boolean) => void
  showPrerequisites: boolean
  setShowPrerequisites: (fn: (v: boolean) => boolean) => void
  showCrossBook: boolean
  setShowCrossBook: (fn: (v: boolean) => boolean) => void
  setShowNotes: (fn: (v: boolean) => boolean) => void
  showRetention: boolean
  setShowRetention: (fn: (v: boolean) => boolean) => void
  // Needs Attention
  masteryData: MasteryConceptsResponse | undefined
  onSetSearch: (v: string) => void
  // Entity types
  allEntityTypes: readonly EntityType[]
  activeTypes: Set<string>
  onToggleEntityType: (type: EntityType) => void
  onSelectAllEntityTypes: () => void
  onDeselectAllEntityTypes: () => void
  // Cluster
  clusterViewEnabled: boolean
  setClusterViewEnabled: (fn: (v: boolean) => boolean) => void
}

export function VizSidebar(props: VizSidebarProps) {
  const {
    viewMode,
    docPickerSearch,
    onDocPickerSearchChange,
    onClearGlobalSearch,
    activeDocumentId,
    onDocSelect,
    filteredDocList,
    showNotes,
    filteredGraph,
    selectedNoteId,
    onSelectNoteId,
    onClearSelectedNode,
    lpInputDraft,
    onLpInputDraftChange,
    onSetLearningPathStart,
    showDiagramNodes,
    setShowDiagramNodes,
    showPrerequisites,
    setShowPrerequisites,
    showCrossBook,
    setShowCrossBook,
    setShowNotes,
    showRetention,
    setShowRetention,
    masteryData,
    onSetSearch,
    allEntityTypes,
    activeTypes,
    onToggleEntityType,
    onSelectAllEntityTypes,
    onDeselectAllEntityTypes,
    clusterViewEnabled,
    setClusterViewEnabled,
  } = props

  if (viewMode === "tags") return null

  return (
    <div
      className="flex flex-col border-r border-border bg-card/20 overflow-y-auto shrink-0 custom-scrollbar"
      style={{ width: 260 }}
    >
      {/* Browsing / Context Selection */}
      <div className="p-4 py-3 border-b border-border/50">
        <div className="flex items-center gap-2 mb-2.5">
          <Library size={13} className="text-primary/70" />
          <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
            Library
          </span>
        </div>

        {/* Search within Library/Entities */}
        <div className="relative mb-3">
          <Search
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/40"
          />
          <input
            type="text"
            value={docPickerSearch}
            onChange={(e) => {
              onDocPickerSearchChange(e.target.value)
              if (!e.target.value) onClearGlobalSearch()
            }}
            placeholder="Filter documents..."
            className="w-full rounded-lg border border-border bg-background pl-8 pr-3 py-2 text-[11px] text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring"
          />
          {docPickerSearch && (
            <button
              onClick={() => onDocPickerSearchChange("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X size={12} />
            </button>
          )}
        </div>

        {/* Quick select list or "All" toggle */}
        <div className="space-y-0.5 max-h-[220px] overflow-y-auto px-1 -mx-1 custom-scrollbar">
          <button
            onClick={() => onDocSelect(null)}
            className={`flex items-center gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] transition-colors ${
              !activeDocumentId
                ? "bg-primary/10 text-primary font-semibold"
                : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
            }`}
          >
            <BookOpen
              size={12}
              className={!activeDocumentId ? "text-primary" : "text-muted-foreground/50"}
            />
            <span className="truncate">All documents</span>
          </button>

          {filteredDocList.slice(0, 15).map((doc) => (
            <button
              key={doc.id}
              onClick={() => onDocSelect(doc.id)}
              className={`flex items-center gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] transition-colors ${
                activeDocumentId === doc.id
                  ? "bg-primary/10 text-primary font-semibold"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
              }`}
              title={doc.title}
            >
              <FileText
                size={12}
                className={
                  activeDocumentId === doc.id ? "text-primary" : "text-muted-foreground/50"
                }
              />
              <span className="truncate">{doc.title}</span>
            </button>
          ))}

          {filteredDocList.length > 15 && (
            <p className="px-2 py-1 text-[9px] text-muted-foreground/50 italic">
              + {filteredDocList.length - 15} more... search to filter
            </p>
          )}

          {filteredDocList.length === 0 && docPickerSearch && (
            <p className="px-2 py-3 text-[10px] text-muted-foreground/50 text-center italic">
              No matching documents
            </p>
          )}
        </div>
      </div>

      {/* Notes Context section (if notes layer is on) */}
      {showNotes && (
        <div className="p-4 py-3 border-b border-border/50 bg-yellow-50/10">
          <div className="flex items-center gap-2 mb-2.5">
            <StickyNote size={13} className="text-yellow-600/70" />
            <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
              Notes in Context
            </span>
          </div>

          <div className="space-y-0.5 max-h-[160px] overflow-y-auto px-1 -mx-1 custom-scrollbar">
            {!filteredGraph ||
            filteredGraph
              .nodes()
              .filter((n) => filteredGraph.getNodeAttribute(n, "type") === "note").length ===
              0 ? (
              <p className="px-2 py-3 text-[10px] text-muted-foreground/50 text-center italic">
                No notes found in graph
              </p>
            ) : (
              filteredGraph
                .nodes()
                .filter((n) => filteredGraph.getNodeAttribute(n, "type") === "note")
                .slice(0, 10)
                .map((n) => {
                  const label = filteredGraph.getNodeAttribute(n, "label") as string
                  const nodeNoteId = filteredGraph.getNodeAttribute(n, "note_id") as string
                  return (
                    <button
                      key={n}
                      onClick={() => {
                        onSelectNoteId(nodeNoteId)
                        onClearSelectedNode()
                      }}
                      className={`flex items-start gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] transition-colors ${
                        selectedNoteId === nodeNoteId
                          ? "bg-yellow-500/10 text-yellow-700 font-semibold"
                          : "text-muted-foreground hover:bg-yellow-500/5 hover:text-foreground"
                      }`}
                    >
                      <StickyNote size={11} className="mt-0.5 shrink-0 opacity-50" />
                      <span className="line-clamp-2">{label}</span>
                    </button>
                  )
                })
            )}
          </div>
        </div>
      )}

      {/* Learning path: start entity input */}
      {viewMode === "learning_path" && (
        <div className="p-4 border-b border-border/50">
          <p className="mb-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
            Start Entity
          </p>
          <div className="flex gap-1.5">
            <input
              type="text"
              value={lpInputDraft}
              onChange={(e) => onLpInputDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSetLearningPathStart(lpInputDraft.trim())
              }}
              placeholder="Concept name..."
              className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <button
              onClick={() => onSetLearningPathStart(lpInputDraft.trim())}
              className="rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Go
            </button>
          </div>
          <p className="mt-1.5 text-[10px] text-muted-foreground/60">
            Orange arrows show prerequisite chains
          </p>
        </div>
      )}

      {/* Layers section */}
      <div className="p-4 border-b border-border/50">
        <div className="flex items-center gap-2 mb-3">
          <Eye size={13} className="text-primary/70" />
          <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
            Layers
          </span>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          {[
            {
              label: "Diagrams",
              checked: showDiagramNodes,
              toggle: () => setShowDiagramNodes((v) => !v),
              color: "#14b8a6",
            },
            {
              label: "Prerequisites",
              checked: showPrerequisites,
              toggle: () => setShowPrerequisites((v) => !v),
              color: PREREQ_EDGE_COLOR,
            },
            {
              label: "Cross-book",
              checked: showCrossBook,
              toggle: () => setShowCrossBook((v) => !v),
              color: SAME_CONCEPT_COLOR,
            },
            {
              label: "Notes",
              checked: showNotes,
              toggle: () => setShowNotes((v) => !v),
              color: NOTE_NODE_COLOR,
            },
            {
              label: "Retention",
              checked: showRetention,
              toggle: () => setShowRetention((v) => !v),
              color: "#22c55e",
            },
          ].map((layer) => (
            <button
              key={layer.label}
              onClick={layer.toggle}
              className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-all ${
                layer.checked
                  ? "bg-accent/60 text-foreground border border-border"
                  : "text-muted-foreground/60 border border-transparent hover:bg-accent/30"
              }`}
            >
              <span
                className={`inline-block h-2 w-2 rounded-full shrink-0 transition-opacity ${layer.checked ? "opacity-100" : "opacity-30"}`}
                style={{ backgroundColor: layer.color }}
              />
              <span className="truncate font-medium">{layer.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Needs Attention panel -- visible when retention overlay is active */}
      {showRetention &&
        masteryData?.concepts &&
        masteryData.concepts.filter((c) => c.no_flashcards || c.mastery < 0.3).length > 0 && (
          <div className="p-4 py-3 border-b border-border/50">
            <div className="flex items-center gap-2 mb-2.5">
              <AlertTriangle size={13} className="text-amber-500/70" />
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
                Needs Attention
              </span>
            </div>
            <p className="text-[10px] text-muted-foreground/60 mb-2">
              Concepts with weak retention or no flashcards
            </p>
            <div className="space-y-0.5 max-h-[200px] overflow-y-auto px-1 -mx-1 custom-scrollbar">
              {masteryData.concepts
                .filter((c) => c.no_flashcards || c.mastery < 0.3)
                .slice(0, 15)
                .map((c) => (
                  <button
                    key={c.concept}
                    onClick={() => onSetSearch(c.concept)}
                    className="flex items-center justify-between gap-2 w-full text-left px-2 py-1.5 rounded-md text-[11px] text-muted-foreground hover:bg-accent/50 hover:text-foreground transition-colors"
                  >
                    <span className="flex items-center gap-1.5 truncate min-w-0">
                      <span
                        className="inline-block h-2 w-2 rounded-full shrink-0"
                        style={{
                          backgroundColor: c.no_flashcards
                            ? BLIND_SPOT_COLOR
                            : masteryColor(c.mastery),
                        }}
                      />
                      <span className="truncate">{c.concept}</span>
                    </span>
                    <span
                      className={`text-[10px] font-mono shrink-0 ${
                        c.no_flashcards
                          ? "text-muted-foreground/40"
                          : c.mastery < 0.15
                            ? "text-red-500"
                            : "text-amber-500"
                      }`}
                    >
                      {c.no_flashcards ? "blind spot" : `${Math.round(c.mastery * 100)}%`}
                    </span>
                  </button>
                ))}
            </div>
          </div>
        )}

      {/* Entity type filter */}
      <div className="p-4 flex-1">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Filter size={13} className="text-primary/70" />
            <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">
              Entity Types
            </span>
          </div>
          <div className="flex gap-1">
            <button
              onClick={onSelectAllEntityTypes}
              className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-primary hover:bg-primary/10 transition-colors"
            >
              All
            </button>
            <span className="text-border">|</span>
            <button
              onClick={onDeselectAllEntityTypes}
              className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground hover:bg-accent transition-colors"
            >
              None
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {allEntityTypes.map((type) => (
            <button
              key={type}
              onClick={() => onToggleEntityType(type)}
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all ${
                activeTypes.has(type)
                  ? "bg-foreground/10 text-foreground border border-border shadow-sm"
                  : "text-muted-foreground/40 border border-transparent hover:text-muted-foreground hover:bg-accent/30"
              }`}
            >
              <span
                className={`inline-block h-2 w-2 rounded-full shrink-0 transition-opacity ${activeTypes.has(type) ? "opacity-100" : "opacity-25"}`}
                style={{ backgroundColor: TYPE_COLORS[type] }}
              />
              {type.toLowerCase().replace(/_/g, " ")}
            </button>
          ))}
        </div>

        {/* Cluster view toggle */}
        <div className="mt-4 pt-3 border-t border-border/50">
          <button
            onClick={() => setClusterViewEnabled((v) => !v)}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs w-full transition-all ${
              clusterViewEnabled
                ? "bg-primary/10 text-primary border border-primary/30"
                : "text-muted-foreground border border-transparent hover:bg-accent/30"
            }`}
          >
            <Network size={13} />
            <span className="font-medium">Cluster view</span>
            <span className="ml-auto text-[10px] text-muted-foreground">&gt;200 nodes</span>
          </button>
        </div>
      </div>
    </div>
  )
}
