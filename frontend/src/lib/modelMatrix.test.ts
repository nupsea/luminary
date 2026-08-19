import { describe, expect, it } from "vitest"
import type { EvalRunFull } from "@/components/evals/types"
import { buildModelMatrix, formatStructural, isStructural } from "./modelMatrix"

function run(over: Partial<EvalRunFull> & { model: string }): EvalRunFull {
  const { model, ...rest } = over
  return {
    id: `${model}-${rest.eval_kind ?? "run"}-${rest.run_at ?? "1"}`,
    dataset_name: "flashcards",
    run_at: "2026-08-16T10:00:00Z",
    hit_rate_5: null,
    mrr: null,
    faithfulness: null,
    answer_relevance: null,
    routing_accuracy: null,
    per_route: null,
    ablation_metrics: null,
    eval_kind: "flashcard",
    model_used: "no-judge",
    citation_support_rate: null,
    extra_metrics: {
      environment: { generation_model: model, library: { documents: 52, chunks: 207047 } },
    },
    ...rest,
  } as EvalRunFull
}

describe("isStructural", () => {
  it("keeps the counters that move with the model", () => {
    for (const key of ["first_pass_rate", "card_reject_rate", "repair_fenced", "generation_rate"]) {
      expect(isStructural(key)).toBe(true)
    }
  })

  it("excludes judged scores and retrieval metrics", () => {
    for (const key of ["faithfulness", "factuality", "hit_rate_5", "mrr", "ndcg_10"]) {
      expect(isStructural(key)).toBe(false)
    }
  })

  it("excludes the metrics library state decides", () => {
    expect(isStructural("cards_returned")).toBe(false)
    expect(isStructural("cards_deduped")).toBe(false)
  })
})

describe("buildModelMatrix", () => {
  it("puts one column per model and one row per metric", () => {
    const matrix = buildModelMatrix([
      run({
        model: "ollama/llama3.2",
        extra_metrics: {
          environment: { generation_model: "ollama/llama3.2" },
          first_pass_rate: 0.4,
          faithfulness: 0.9,
        },
      }),
      run({
        model: "ollama/qwen3.5:4b",
        extra_metrics: {
          environment: { generation_model: "ollama/qwen3.5:4b" },
          first_pass_rate: 0.95,
          faithfulness: 0.4,
        },
      }),
    ])

    expect(matrix.models).toEqual(["ollama/llama3.2", "ollama/qwen3.5:4b"])
    expect(matrix.rows.map((r) => r.key)).toEqual(["flashcard.first_pass_rate"])
    expect(matrix.rows[0].cells).toEqual({
      "ollama/llama3.2": 0.4,
      "ollama/qwen3.5:4b": 0.95,
    })
  })

  it("flags a metric that came out identical on two models", () => {
    const matrix = buildModelMatrix([
      run({
        model: "a",
        extra_metrics: { environment: { generation_model: "a" }, first_pass_rate: 0.5 },
      }),
      run({
        model: "b",
        extra_metrics: { environment: { generation_model: "b" }, first_pass_rate: 0.5 },
      }),
    ])

    expect(matrix.identicalKeys).toEqual(["flashcard.first_pass_rate"])
  })

  it("does not flag a single model's own numbers as identical", () => {
    const matrix = buildModelMatrix([
      run({
        model: "a",
        extra_metrics: { environment: { generation_model: "a" }, first_pass_rate: 0.5 },
      }),
    ])

    expect(matrix.identicalKeys).toEqual([])
  })

  it("keeps a model's newest run per kind rather than adding a column", () => {
    const matrix = buildModelMatrix([
      run({
        model: "a",
        run_at: "2026-08-15T10:00:00Z",
        extra_metrics: { environment: { generation_model: "a" }, first_pass_rate: 0.1 },
      }),
      run({
        model: "a",
        run_at: "2026-08-16T10:00:00Z",
        extra_metrics: { environment: { generation_model: "a" }, first_pass_rate: 0.9 },
      }),
    ])

    expect(matrix.models).toEqual(["a"])
    expect(matrix.rows[0].cells).toEqual({ a: 0.9 })
  })

  it("separates the same metric measured under different eval kinds", () => {
    const matrix = buildModelMatrix([
      run({
        model: "a",
        eval_kind: "flashcard",
        extra_metrics: { environment: { generation_model: "a" }, first_pass_rate: 0.1 },
      }),
      run({
        model: "a",
        eval_kind: "generation",
        extra_metrics: { environment: { generation_model: "a" }, first_pass_rate: 0.8 },
      }),
    ])

    expect(matrix.rows.map((r) => r.key)).toEqual([
      "flashcard.first_pass_rate",
      "generation.first_pass_rate",
    ])
  })

  it("records every provenance it drew from, so incomparable runs are visible", () => {
    const matrix = buildModelMatrix([
      run({
        model: "a",
        extra_metrics: {
          environment: { generation_model: "a", library: { documents: 52, chunks: 1 } },
          first_pass_rate: 0.1,
        },
      }),
      run({
        model: "b",
        extra_metrics: {
          environment: { generation_model: "b", library: { documents: 9, chunks: 2 } },
          first_pass_rate: 0.2,
        },
      }),
    ])

    expect(matrix.fingerprints.length).toBe(2)
  })

  it("skips runs with no recorded model rather than inventing a column", () => {
    const matrix = buildModelMatrix([
      run({ model: "a", extra_metrics: { first_pass_rate: 0.1 } }),
    ])

    expect(matrix.models).toEqual([])
  })
})

describe("formatStructural", () => {
  it("reads a rate as a percentage and a count as itself", () => {
    expect(formatStructural("first_pass_rate", 0.965)).toBe("96.5%")
    expect(formatStructural("routing_accuracy", 0.8621)).toBe("86.2%")
    expect(formatStructural("cards_gated", 105)).toBe("105")
  })
})
