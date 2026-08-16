import { describe, expect, it } from "vitest"
import type { LabMetricRow, LabRun, LabTask } from "@/lib/modelLabApi"
import {
  estimateSeconds,
  expandTasks,
  formatDuration,
  formatMetric,
  mutatingStages,
  progressPct,
  rowsByTier,
  verdict,
} from "./modelLab"

const TASKS: LabTask[] = [
  { key: "intent", label: "Intent routing", description: "", typical_seconds: 60, mutates_library: false },
  { key: "flashcards", label: "Flashcards", description: "", typical_seconds: 300, mutates_library: true },
  { key: "summary", label: "Summaries", description: "", typical_seconds: 180, mutates_library: true },
]

function run(over: Partial<LabRun> = {}): LabRun {
  return {
    id: "r1",
    status: "complete",
    models: ["ollama/a", "ollama/b"],
    tasks: ["intent"],
    started_at: "2026-08-16T10:00:00Z",
    finished_at: "2026-08-16T10:10:00Z",
    total_units: 2,
    completed_units: 2,
    arms: [],
    rows: [],
    separation: { separated: true, separating_metrics: ["intent.routing_accuracy"], unmeasured_tasks: [] },
    error: null,
    restore_error: null,
    ...over,
  }
}

describe("expandTasks", () => {
  it("turns the qa stage into one task per dataset", () => {
    expect(expandTasks(["intent", "qa"], ["book", "legal"])).toEqual([
      "intent",
      "qa:book",
      "qa:legal",
    ])
  })

  it("leaves qa out entirely when no dataset is chosen", () => {
    expect(expandTasks(["intent", "qa"], [])).toEqual(["intent"])
  })
})

describe("estimateSeconds", () => {
  it("scales with the number of models", () => {
    expect(estimateSeconds(TASKS, ["intent"], [], 1, 0)).toBe(60)
    expect(estimateSeconds(TASKS, ["intent"], [], 4, 0)).toBe(240)
  })

  it("prices qa from the question count actually requested", () => {
    expect(estimateSeconds(TASKS, ["qa"], ["book"], 1, 10)).toBe(10 * 32)
    expect(estimateSeconds(TASKS, ["qa"], ["book", "legal"], 1, 10)).toBe(2 * 10 * 32)
  })

  it("falls back to the full golden when no cap is set", () => {
    expect(estimateSeconds(TASKS, ["qa"], ["book"], 1, 0)).toBe(40 * 32)
  })
})

describe("formatDuration", () => {
  it("reads in the unit a human would use", () => {
    expect(formatDuration(45)).toBe("45s")
    expect(formatDuration(600)).toBe("10 min")
    expect(formatDuration(7200)).toBe("2h")
    expect(formatDuration(5400)).toBe("1h 30m")
    expect(formatDuration(9000)).toBe("2h 30m")
  })
})

describe("mutatingStages", () => {
  it("names the stages that write to the library, so the warning is specific", () => {
    expect(mutatingStages(TASKS, ["intent", "flashcards"])).toEqual(["Flashcards"])
    expect(mutatingStages(TASKS, ["intent"])).toEqual([])
  })
})

describe("progressPct", () => {
  it("reports completed units out of total", () => {
    expect(progressPct(run({ total_units: 4, completed_units: 1 }))).toBe(25)
  })

  it("does not divide by zero before a run has units", () => {
    expect(progressPct(run({ total_units: 0, completed_units: 0 }))).toBe(0)
  })
})

describe("rowsByTier", () => {
  const rows: LabMetricRow[] = [
    { key: "a.first_pass_rate", metric: "first_pass_rate", tier: "structural", values: {}, identical: false },
    { key: "a.faithfulness", metric: "faithfulness", tier: "quality", values: {}, identical: false },
    { key: "a.hit_rate_5", metric: "hit_rate_5", tier: "excluded", values: {}, identical: false },
  ]

  it("puts structural first and drops the excluded tier entirely", () => {
    const groups = rowsByTier(rows)

    expect(groups.map((g) => g.tier)).toEqual(["structural", "quality"])
  })

  it("omits a tier with no rows rather than showing an empty heading", () => {
    expect(rowsByTier([rows[0]]).map((g) => g.tier)).toEqual(["structural"])
  })
})

describe("formatMetric", () => {
  it("reads a rate as a percentage and a count as itself", () => {
    expect(formatMetric("first_pass_rate", 0.965)).toBe("96.5%")
    expect(formatMetric("citation_coverage", 0.7179)).toBe("71.8%")
    expect(formatMetric("cards_gated", 108)).toBe("108")
    expect(formatMetric("anything", null)).toBe("—")
  })
})

describe("verdict", () => {
  it("says what a separation means", () => {
    expect(verdict(run()).tone).toBe("good")
  })

  it("blames the instrument, not the models, when nothing separates", () => {
    const v = verdict(
      run({ separation: { separated: false, separating_metrics: [], unmeasured_tasks: [] } }),
    )

    expect(v.tone).toBe("bad")
    expect(v.text).toMatch(/about the instrument/)
  })

  it("refuses to call one model a comparison", () => {
    expect(verdict(run({ models: ["ollama/a"] })).tone).toBe("warn")
  })

  it("does not present a cancelled run as a result", () => {
    const v = verdict(run({ status: "cancelled" }))

    expect(v.tone).toBe("warn")
    expect(v.text).toMatch(/not a comparison/)
  })
})
