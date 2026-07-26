// Node types are scoped to this file rather than added to tsconfig.app.json,
// so app code still cannot reach for filesystem APIs.
/// <reference types="node" />
import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"
import { isStale, metricColor, shippedAblationArm, THRESHOLDS, timeAgo } from "./thresholds"
import type { EvalRunFull } from "./types"

/** Parse THRESHOLDS out of evals/run_eval.py, the source of truth. */
function backendThresholds(): Record<string, number> {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..")
  const src = readFileSync(resolve(root, "evals/run_eval.py"), "utf8")
  const block = /^THRESHOLDS\s*=\s*\{([\s\S]*?)^\}/m.exec(src)
  if (!block) throw new Error("THRESHOLDS block not found in evals/run_eval.py")
  const out: Record<string, number> = {}
  for (const m of block[1].matchAll(/"([a-z_0-9]+)"\s*:\s*([0-9.]+)/g)) {
    out[m[1]] = Number(m[2])
  }
  return out
}

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
  // Read the backend rather than restate it. The previous version asserted
  // against copied literals, so when the backend re-baselined faithfulness to
  // a 0.30 collapse floor this kept passing on the retired 0.65 bar and the UI
  // painted healthy runs amber.
  it("matches the backend gates in evals/run_eval.py", () => {
    const backend = backendThresholds()
    expect(Object.keys(backend).length).toBeGreaterThan(0)
    for (const [metric, value] of Object.entries(THRESHOLDS)) {
      expect(backend[metric], `${metric} drifted from evals/run_eval.py`).toBe(value)
    }
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
