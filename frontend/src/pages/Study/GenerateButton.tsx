// GenerateButton -- single "Generate Cards" button with a
// chevron disclosure that reveals advanced options (mode, scope,
// section, difficulty, count). Replaces the older GeneratePanel +
// SmartGeneratePanel split. The "smart" path picks a mode based on
// the learner's mastery via buildSmartGenerateParams.

import { useState } from "react"
import { ChevronDown, ChevronUp, Loader2, Zap } from "lucide-react"

import { buildSmartGenerateParams, computeMasteryPct, selectSmartMode } from "@/lib/studyUtils"

import type { Flashcard, SectionItem } from "./types"

const COUNT_OPTIONS = [5, 10, 20, 50]
const DIFFICULTY_OPTIONS = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
]

const SMART_MODE_LABEL: Record<string, string> = {
  basic: "basic cards",
  feynman: "Feynman-style questions",
  cloze: "cloze cards",
}

const GENERATE_MODE_OPTIONS = [
  { value: "basic", label: "Basic" },
  { value: "graph", label: "Graph (entities)" },
  { value: "cloze", label: "Cloze" },
  { value: "technical", label: "Technical" },
]

interface GenerateButtonProps {
  documentId: string
  sections: SectionItem[]
  cards: Flashcard[]
  onGenerate: (req: {
    scope: "full" | "section"
    section_heading: string | null
    count: number
    difficulty: "easy" | "medium" | "hard"
  }) => void
  onGenerateFromGraph: (k: number) => void
  onGenerateCloze: (sectionId: string, count: number) => void
  onGenerateTechnical: (req: {
    scope: "full" | "section"
    section_heading: string | null
    count: number
  }) => void
  isGenerating: boolean
  isClozeGenerating: boolean
}

export function GenerateButton({
  documentId,
  sections,
  cards,
  onGenerate,
  onGenerateFromGraph,
  onGenerateCloze,
  onGenerateTechnical,
  isGenerating,
  isClozeGenerating,
}: GenerateButtonProps) {
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [scope, setScope] = useState<"full" | "section">("full")
  const [sectionHeading, setSectionHeading] = useState<string | null>(null)
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium")
  const [mode, setMode] = useState<"basic" | "graph" | "cloze" | "technical">("basic")
  const [count, setCount] = useState(10)
  const [clozeSectionId, setClozeSectionId] = useState<string | null>(null)

  const masteryPct = computeMasteryPct(cards)
  const isAnyGenerating = isGenerating || isClozeGenerating

  function handleSmartGenerate() {
    const params = buildSmartGenerateParams(masteryPct, documentId)
    if (params.smart_mode === "feynman") {
      onGenerateFromGraph(5)
    } else if (params.smart_mode === "cloze") {
      const firstSection = sections[0]
      if (firstSection) {
        onGenerateCloze(firstSection.id, 5)
      } else {
        onGenerate({ scope: "full", section_heading: null, count: 10, difficulty: "medium" })
      }
    } else {
      onGenerate({
        scope: params.scope,
        section_heading: params.section_heading,
        count: params.count,
        difficulty: params.difficulty,
      })
    }
  }

  function handleAdvancedGenerate() {
    if (mode === "technical") {
      onGenerateTechnical({ scope, section_heading: sectionHeading, count })
    } else if (mode === "graph") {
      onGenerateFromGraph(5)
    } else if (mode === "cloze") {
      if (clozeSectionId) {
        onGenerateCloze(clozeSectionId, count)
      }
    } else {
      onGenerate({ scope, section_heading: sectionHeading, count, difficulty })
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <button
          onClick={handleSmartGenerate}
          disabled={isAnyGenerating || !documentId}
          className="flex items-center gap-2 rounded-l bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isAnyGenerating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Zap size={14} />
          )}
          Generate Cards
        </button>
        <button
          onClick={() => setOptionsOpen((v) => !v)}
          disabled={!documentId}
          className="flex items-center rounded-r border-l border-primary-foreground/20 bg-primary px-2 py-2 text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          aria-label="Toggle generate options"
        >
          {optionsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>
      {!isAnyGenerating && (
        <span className="text-xs text-muted-foreground">
          Adaptive: {SMART_MODE_LABEL[selectSmartMode(masteryPct)] ?? "basic cards"}
        </span>
      )}
      {isAnyGenerating && (
        <span className="text-xs text-muted-foreground">
          Generating {SMART_MODE_LABEL[selectSmartMode(masteryPct)]}...
        </span>
      )}

      {/* Disclosure panel: advanced options */}
      {optionsOpen && (
        <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/30 p-3 mt-1">
          <div className="flex flex-wrap items-end gap-3">
            {/* Mode */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Mode</label>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as typeof mode)}
                className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {GENERATE_MODE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            {/* Scope (only for basic mode) */}
            {mode === "basic" && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">Scope</label>
                <select
                  value={scope}
                  onChange={(e) => {
                    const v = e.target.value as "full" | "section"
                    setScope(v)
                    if (v === "full") setSectionHeading(null)
                  }}
                  className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="full">Full document</option>
                  <option value="section">By section</option>
                </select>
              </div>
            )}

            {/* Section picker for basic + section scope */}
            {mode === "basic" && scope === "section" && sections.length > 0 && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">Section</label>
                <select
                  value={sectionHeading ?? ""}
                  onChange={(e) => setSectionHeading(e.target.value || null)}
                  className="max-w-[240px] rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">Select section...</option>
                  {sections.map((s) => (
                    <option key={s.id} value={s.heading}>{s.heading}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Section picker for cloze mode (required) */}
            {mode === "cloze" && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">
                  Section <span className="text-red-500">*</span>
                </label>
                <select
                  value={clozeSectionId ?? ""}
                  onChange={(e) => setClozeSectionId(e.target.value || null)}
                  className="max-w-[240px] rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">Select a section...</option>
                  {sections.map((s) => (
                    <option key={s.id} value={s.id}>{s.heading}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Difficulty (basic mode only) */}
            {mode === "basic" && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-muted-foreground">Difficulty</label>
                <select
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value as "easy" | "medium" | "hard")}
                  className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {DIFFICULTY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Count */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Count</label>
              <select
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                className="rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {COUNT_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n} cards</option>
                ))}
              </select>
            </div>

            <button
              onClick={handleAdvancedGenerate}
              disabled={
                isAnyGenerating ||
                (mode === "basic" && scope === "section" && !sectionHeading) ||
                (mode === "cloze" && !clozeSectionId)
              }
              className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {isAnyGenerating && <Loader2 size={14} className="animate-spin" />}
              Generate
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
