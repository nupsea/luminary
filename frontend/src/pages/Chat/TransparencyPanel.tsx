// Per-message transparency panel: confidence badge + collapsible "How I Answered" details (S158).

import { Info } from "lucide-react"
import { useState } from "react"

import { TRANSPARENCY_BADGE_CLASS, STRATEGY_LABEL } from "./constants"
import type { TransparencyInfo } from "./types"
import { TRANSPARENCY_DEFAULT_OPEN } from "@/lib/chatSettingsUtils"

export function TransparencyPanel({ transparency }: { transparency: TransparencyInfo }) {
  const [open, setOpen] = useState(TRANSPARENCY_DEFAULT_OPEN)
  const badgeClass =
    TRANSPARENCY_BADGE_CLASS[transparency.confidence_level] ??
    TRANSPARENCY_BADGE_CLASS["low"]

  return (
    <div className="mt-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${badgeClass}`}
        >
          {transparency.confidence_level} confidence
        </span>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-muted-foreground hover:text-foreground transition-colors"
          aria-expanded={open}
          title={open ? "Hide retrieval details" : "How I answered"}
        >
          <Info size={13} />
        </button>
      </div>
      {open && (
        <div className="mt-2 rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground space-y-1">
          <div>
            <span className="font-medium text-foreground">Strategy:</span>{" "}
            {STRATEGY_LABEL[transparency.strategy_used] ?? transparency.strategy_used}
          </div>
          <div>
            <span className="font-medium text-foreground">Sources:</span>{" "}
            {transparency.chunk_count} chunk{transparency.chunk_count !== 1 ? "s" : ""}
            {transparency.section_count > 0
              ? ` from ${transparency.section_count} section${transparency.section_count !== 1 ? "s" : ""}`
              : ""}
          </div>
          {transparency.augmented && (
            <div className="italic">Context was extended after initial low confidence</div>
          )}
        </div>
      )}
    </div>
  )
}
