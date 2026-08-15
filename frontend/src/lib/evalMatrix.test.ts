import { describe, expect, it } from "vitest"

import type { EvalRunFull } from "@/components/evals/types"
import {
  fingerprintOf,
  groupByComparability,
  isMixed,
  latestRetrievalPerDataset,
  toKindRow,
} from "./evalMatrix"

function run(over: Partial<EvalRunFull> = {}): EvalRunFull {
  return {
    id: "r1",
    dataset_name: "book",
    run_at: "2026-08-15T10:00:00+00:00",
    hit_rate_5: 0.5,
    mrr: 0.4,
    faithfulness: null,
    answer_relevance: null,
    routing_accuracy: null,
    per_route: null,
    ablation_metrics: null,
    eval_kind: "retrieval",
    model_used: "no-llm",
    citation_support_rate: null,
    extra_metrics: {
      ndcg_10: 0.48,
      environment: {
        library: { documents: 52, chunks: 207047 },
        embedding_model: "BAAI/bge-small-en-v1.5",
        rerank_model: "cross-encoder/ms-marco-MiniLM-L-12-v2",
        chat_model: "ollama/qwen2.5:14b-instruct",
      },
    },
    ...over,
  }
}

describe("latestRetrievalPerDataset", () => {
  it("keeps the newest run per dataset", () => {
    const rows = latestRetrievalPerDataset([
      run({ id: "old", run_at: "2026-08-01T10:00:00+00:00", hit_rate_5: 0.1 }),
      run({ id: "new", run_at: "2026-08-15T10:00:00+00:00", hit_rate_5: 0.9 }),
    ])
    expect(rows).toHaveLength(1)
    expect(rows[0].id).toBe("new")
  })

  it("drops rows that measured nothing", () => {
    expect(latestRetrievalPerDataset([run({ hit_rate_5: null, mrr: null })])).toHaveLength(0)
    expect(latestRetrievalPerDataset([run({ status: "failed" })])).toHaveLength(0)
  })

  it("excludes a series aggregate, which is made of runs already listed", () => {
    const rows = latestRetrievalPerDataset([
      run({ id: "one", eval_kind: "citation" }),
      run({ id: "agg", eval_kind: "citation-series", run_at: "2026-08-16T10:00:00+00:00" }),
    ])
    expect(rows.map((r) => r.id)).toEqual(["one"])
  })
})

describe("comparability", () => {
  it("separates rows measured against a different corpus", () => {
    const grown = run({
      dataset_name: "paper",
      extra_metrics: {
        environment: { library: { documents: 53, chunks: 210000 } },
      },
    })
    const groups = groupByComparability([run(), grown])
    expect(groups).toHaveLength(2)
    expect(isMixed(groups)).toBe(true)
  })

  it("keeps rows from one state together", () => {
    const groups = groupByComparability([run({ dataset_name: "book" }), run({ dataset_name: "d2l" })])
    expect(groups).toHaveLength(1)
    expect(isMixed(groups)).toBe(false)
    expect(groups[0].rows).toHaveLength(2)
  })

  it("sorts worst first so the kinds needing work read at the top", () => {
    const groups = groupByComparability([
      run({ dataset_name: "notes", hit_rate_5: 1.0 }),
      run({ dataset_name: "book_frankenstein", hit_rate_5: 0.35 }),
      run({ dataset_name: "d2l", hit_rate_5: 0.84 }),
    ])
    expect(groups[0].rows.map((r) => r.dataset)).toEqual([
      "book_frankenstein",
      "d2l",
      "notes",
    ])
  })

  it("marks a run with no provenance rather than assuming it matches", () => {
    const bare = run({ extra_metrics: { ndcg_10: 0.4 } })
    expect(fingerprintOf(bare)).toBe("unrecorded")
    expect(isMixed(groupByComparability([run(), bare]))).toBe(true)
  })
})

describe("toKindRow", () => {
  it("surfaces a metric that has no column, so a new one needs no UI change", () => {
    const row = toKindRow(
      run({
        extra_metrics: {
          ndcg_10: 0.48,
          boundary_misses: 2,
          first_pass_rate: 0.0,
          some_future_metric: 0.7,
        },
      })
    )
    expect(row.boundaryMisses).toBe(2)
    expect(row.extras).toContainEqual(["some_future_metric", 0.7])
    expect(row.extras).toContainEqual(["first_pass_rate", 0])
    // ndcg_10 has its own column and must not be repeated in the generic list.
    expect(row.extras.map(([k]) => k)).not.toContain("ndcg_10")
  })
})

describe("scoped and unscoped are different measurements", () => {
  it("a corpus_routing row never stands in for a scoped retrieval row", () => {
    const rows = latestRetrievalPerDataset([
      run({ id: "scoped", dataset_name: "book", hit_rate_5: 0.525 }),
      run({
        id: "routing",
        dataset_name: "book",
        eval_kind: "corpus_routing",
        hit_rate_5: 0.55,
        run_at: "2026-08-16T10:00:00+00:00",
      }),
    ])
    expect(rows.map((r) => r.id)).toEqual(["scoped"])
  })
})

describe("scope is part of a row's identity", () => {
  const withScope = (scope: string, hr: number, at: string) =>
    run({
      id: scope,
      dataset_name: "paper",
      hit_rate_5: hr,
      run_at: at,
      extra_metrics: { environment: { library: { documents: 52, chunks: 207047 }, scope } },
    })

  it("keeps both the scoped and the unscoped latest run for one dataset", () => {
    const rows = latestRetrievalPerDataset([
      withScope("scoped", 0.85, "2026-08-15T10:00:00+00:00"),
      withScope("unscoped", 0.55, "2026-08-15T11:00:00+00:00"),
    ])
    expect(rows.map((r) => r.id).sort()).toEqual(["scoped", "unscoped"])
  })

  it("groups them apart, because one is not a newer measurement of the other", () => {
    const groups = groupByComparability([
      withScope("scoped", 0.85, "2026-08-15T10:00:00+00:00"),
      withScope("unscoped", 0.55, "2026-08-15T11:00:00+00:00"),
    ])
    expect(groups).toHaveLength(2)
    expect(isMixed(groups)).toBe(true)
  })
})
