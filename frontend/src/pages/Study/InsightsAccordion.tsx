// InsightsAccordion (S185) -- collapsible wrapper that merges
// HealthReportPanel + DeckHealthPanel + StrugglingPanel under a
// single "Insights" disclosure. Section enumeration is driven by
// INSIGHTS_SECTIONS so the order/visibility is test-controlled.

import { useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"

import { INSIGHTS_SECTIONS, computeMasteryPct } from "@/lib/studyUtils"

import { DeckHealthPanel } from "./DeckHealthPanel"
import { HealthReportPanel } from "./HealthReportPanel"
import { StrugglingPanel } from "./StrugglingPanel"
import type { Flashcard } from "./types"

interface InsightsAccordionProps {
  documentId: string
  cards: Flashcard[]
}

export function InsightsAccordion({ documentId, cards }: InsightsAccordionProps) {
  const [isOpen, setIsOpen] = useState(false)
  const totalCards = cards.length
  const masteredPct = Math.round(computeMasteryPct(cards))

  return (
    <section className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <button
        className="flex items-center justify-between text-left"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="text-base font-semibold text-foreground">
          Insights ({totalCards} card{totalCards !== 1 ? "s" : ""}, {masteredPct}% mastered)
        </span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-4 pt-2">
          {/* Sections driven by INSIGHTS_SECTIONS constant */}
          {INSIGHTS_SECTIONS.includes("health_report") && (
            <HealthReportPanel documentId={documentId} />
          )}
          {INSIGHTS_SECTIONS.includes("bloom_audit") && (
            <DeckHealthPanel documentId={documentId} />
          )}
          {INSIGHTS_SECTIONS.includes("struggling") && (
            <StrugglingPanel documentId={documentId} />
          )}
        </div>
      )}
    </section>
  )
}
