// Top header bar of the Viz page: title + view-mode pills + scope
// toggle + node/edge count badge. Pure presentation -- the parent
// owns the state and passes the values + callbacks in.

import type { LucideIcon } from "lucide-react"

interface ViewModeOption {
  key: string
  label: string
  icon: LucideIcon
}

interface HeaderBarProps {
  viewModes: ViewModeOption[]
  viewMode: string
  onSelectViewMode: (key: string) => void
  scope: "document" | "all"
  onSelectScope: (scope: "document" | "all") => void
  graphStats: { nodeCount: number; edgeCount: number } | null
}

export function HeaderBar({
  viewModes,
  viewMode,
  onSelectViewMode,
  scope,
  onSelectScope,
  graphStats,
}: HeaderBarProps) {
  return (
    <div className="flex items-center justify-between border-b border-border bg-card/30 px-6 py-2.5 backdrop-blur-md shrink-0">
      <div className="flex items-center gap-6">
        <h1 className="text-xl font-bold tracking-tight text-foreground">Viz</h1>

        {/* View mode pills */}
        <div className="flex items-center gap-1 rounded-full border border-border bg-muted/30 p-0.5">
          {viewModes.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => onSelectViewMode(key)}
              className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium transition-all ${
                viewMode === key
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
              }`}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        {/* Scope toggle -- hidden for Tags mode */}
        {viewMode !== "tags" && (
          <div className="flex items-center gap-1 rounded-full border border-border bg-muted/30 p-0.5">
            {(["document", "all"] as const).map((s) => (
              <button
                key={s}
                onClick={() => onSelectScope(s)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-all ${
                  scope === s
                    ? "bg-secondary text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {s === "document" ? "This doc" : "All docs"}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Node + edge count badge */}
      <div className="flex items-center gap-3">
        {graphStats && (
          <div className="flex items-center gap-2 rounded-full border border-border bg-card/50 px-3 py-1">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase">
              {graphStats.nodeCount} nodes
            </span>
            <span className="text-border">|</span>
            <span className="text-[10px] font-semibold text-muted-foreground uppercase">
              {graphStats.edgeCount} edges
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
