import { describe, expect, it } from "vitest"
import { isStale, metricColor, shippedAblationArm, THRESHOLDS, timeAgo } from "./thresholds"
import type { EvalRunFull } from "./types"

const NOW = Date.parse("2026-07-02T12:00:00Z")

function run(overrides: Partial<EvalRunFull>): EvalRunFull {
  return {
    id: "r1",
    dataset_name: "ds",
    run_at: "2026-07-01T00:00:00Z",
    hit_rate_5: null,
    mrr: null,
    faithfulness: null,
    answer_relevance: null,
    routing_accuracy: null,
    per_route: null,
    ablation_metrics: null,
    eval_kind: null,
    model_used: "no-llm",
    citation_support_rate: null,
    extra_metrics: null,
    ...overrides,
  }
}

describe("THRESHOLDS", () => {
  it("matches the backend gates in evals/run_eval.py", () => {
    expect(THRESHOLDS.hit_rate_5).toBe(0.5)
    expect(THRESHOLDS.mrr).toBe(0.35)
    expect(THRESHOLDS.faithfulness).toBe(0.65)
  })
})

describe("metricColor", () => {
  it("greens at the gate, ambers near it, mutes below", () => {
    expect(metricColor(0.5, 0.5)).toContain("green")
    expect(metricColor(0.4, 0.5)).toContain("amber")
    expect(metricColor(0.3, 0.5)).toBe("text-muted-foreground")
    expect(metricColor(null, 0.5)).toBe("")
  })
})

describe("timeAgo / isStale", () => {
  it("formats minutes, hours, days", () => {
    expect(timeAgo("2026-07-02T11:30:00Z", NOW)).toBe("30m ago")
    expect(timeAgo("2026-07-02T04:00:00Z", NOW)).toBe("8h ago")
    expect(timeAgo("2026-06-28T12:00:00Z", NOW)).toBe("4d ago")
  })
  it("flags measurements older than the window", () => {
    expect(isStale("2026-06-30T12:00:00Z", 14, NOW)).toBe(false)
    expect(isStale("2026-06-01T12:00:00Z", 14, NOW)).toBe(true)
  })
})

describe("shippedAblationArm", () => {
  it("prefers rrf+rerank, falls back to rrf, else null", () => {
    const full = run({
      eval_kind: "ablation",
      ablation_metrics: {
        rrf: { hit_rate_5: 0.56, mrr: 0.44 },
        "rrf+rerank": { hit_rate_5: 0.63, mrr: 0.53 },
      },
    })
    expect(shippedAblationArm(full)).toEqual({
      label: "rrf+rerank",
      arm: { hit_rate_5: 0.63, mrr: 0.53 },
    })

    const rrfOnly = run({
      eval_kind: "ablation",
      ablation_metrics: { rrf: { hit_rate_5: 0.56, mrr: 0.44 } },
    })
    expect(shippedAblationArm(rrfOnly)?.label).toBe("rrf")

    expect(shippedAblationArm(run({}))).toBeNull()
  })
})
