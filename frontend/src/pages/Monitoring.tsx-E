/**
 * Monitoring tab — complete metrics dashboard.
 *
 * Sections:
 *   1. System Status — Ollama, Phoenix, Langfuse, Active Model
 *   2. RAG Quality — grouped BarChart per dataset (HR@5, MRR, Faithfulness, AR, CP)
 *   3. Retrieval Quality Over Time — HR@5 sparkline per dataset
 *   4. Model Usage — PieChart (local vs cloud) + BarChart (latency by model)
 *   5. Ingestion Queue — in-progress documents
 *   6. Recent Traces — last 50 Phoenix spans
 *   7. Eval Runs — table with HR@5 row coloring
 *
 * Each section fetches independently: if one endpoint fails the rest render normally.
 */


import { useEffect, useState } from "react"

import { EvalTrendsPanel } from "@/components/EvalTrendsPanel"
import { logger } from "@/lib/logger"
import { Skeleton } from "@/components/ui/skeleton"

import {
  EvalHistorySparkline,
  ModelUsageSection,
  RAGQualityChart,
  TracesCard,
} from "./Monitoring/Charts"
import { EvalPanel } from "./Monitoring/EvalPanel"
import { MasteryPanel } from "./Monitoring/MasteryPanel"
import {
  EmptyState,
  MetricCardSkeleton,
  ModelBadge,
  SectionErrorCard,
  SectionSkeleton,
  StatusBadge,
  StatusIndicator,
  TraceDetailPanel,
} from "./Monitoring/SharedUI"
import {
  fetchDocuments,
  fetchEvalHistory,
  fetchEvalRuns,
  fetchLLMSettings,
  fetchModelUsage,
  fetchOverview,
  fetchPhoenixUrl,
  fetchTraces,
} from "./Monitoring/api"
import type {
  Document,
  EvalHistoryItem,
  EvalRun,
  LLMSettings,
  ModelUsageItem,
  MonitoringOverview,
  PhoenixUrl,
  SectionState,
  TraceItem,
  TracesResponse,
} from "./Monitoring/types"
import { initSection } from "./Monitoring/types"

// ---------------------------------------------------------------------------
// Monitoring page
// ---------------------------------------------------------------------------

export default function Monitoring() {
  const [activeTab, setActiveTab] = useState<"overview" | "mastery">("overview")
  const [overviewState, setOverviewState] = useState<SectionState<MonitoringOverview | null>>(
    initSection(null),
  )
  const [tracesState, setTracesState] = useState<SectionState<TracesResponse>>(
    initSection({ traces: [] }),
  )
  const [evalRunsState, setEvalRunsState] = useState<SectionState<EvalRun[]>>(initSection([]))
  const [evalHistState, setEvalHistState] = useState<SectionState<EvalHistoryItem[]>>(
    initSection([]),
  )
  const [modelUsageState, setModelUsageState] = useState<SectionState<ModelUsageItem[]>>(
    initSection([]),
  )
  const [llmState, setLlmState] = useState<SectionState<LLMSettings | null>>(initSection(null))
  const [docsState, setDocsState] = useState<SectionState<Document[]>>(initSection([]))
  const [phoenixUrlState, setPhoenixUrlState] = useState<SectionState<PhoenixUrl | null>>(
    initSection(null),
  )

  const [selectedTrace, setSelectedTrace] = useState<TraceItem | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchOverview()
      .then((d) => {
        if (!cancelled) setOverviewState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "System Status", e)
        if (!cancelled) setOverviewState({ loading: false, data: null, error: true })
      })

    fetchTraces()
      .then((d) => {
        if (!cancelled) setTracesState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Recent Traces", e)
        if (!cancelled) setTracesState({ loading: false, data: { traces: [] }, error: true })
      })

    fetchEvalRuns()
      .then((d) => {
        if (!cancelled) setEvalRunsState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Eval Runs", e)
        if (!cancelled) setEvalRunsState({ loading: false, data: [], error: true })
      })

    fetchEvalHistory()
      .then((d) => {
        if (!cancelled) setEvalHistState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Eval History", e)
        if (!cancelled) setEvalHistState({ loading: false, data: [], error: true })
      })

    fetchModelUsage()
      .then((d) => {
        if (!cancelled) setModelUsageState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Model Usage", e)
        if (!cancelled) setModelUsageState({ loading: false, data: [], error: true })
      })

    fetchLLMSettings()
      .then((d) => {
        if (!cancelled) setLlmState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "LLM Settings", e)
        if (!cancelled) setLlmState({ loading: false, data: null, error: true })
      })

    fetchDocuments()
      .then((d) => {
        if (!cancelled) setDocsState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", "Ingestion Queue", e)
        if (!cancelled) setDocsState({ loading: false, data: [], error: true })
      })

    const loadPhoenixUrl = () => {
      fetchPhoenixUrl()
        .then((d) => {
          if (!cancelled) setPhoenixUrlState({ loading: false, data: d, error: false })
        })
        .catch((e: unknown) => {
          logger.warn("[Monitoring] section failed", "Phoenix URL", e)
          if (!cancelled) setPhoenixUrlState({ loading: false, data: null, error: true })
        })
    }
    loadPhoenixUrl()
    const phoenixInterval = setInterval(loadPhoenixUrl, 30_000)

    return () => {
      cancelled = true
      clearInterval(phoenixInterval)
    }
  }, [])

  const ollamaOnline = llmState.data?.processing_mode === "local"
  const activeModel = llmState.data?.active_model ?? overviewState.data?.llm_status ?? "—"
  const ingestingDocs = docsState.data.filter((d) => d.stage !== "complete")

  return (
    <div className="flex flex-col gap-8 px-6 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Monitoring</h1>
        {/* Tab bar */}
        <div className="flex gap-1 rounded-lg border border-border bg-secondary p-1">
          {(["overview", "mastery"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                activeTab === tab
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab === "overview" ? "Overview" : "Mastery"}
            </button>
          ))}
        </div>
      </div>

      {/* Mastery tab */}
      {activeTab === "mastery" && (
        <MasteryPanel documents={docsState.data} />
      )}

      {/* Overview tab sections -- hidden when mastery tab is active */}
      {activeTab === "overview" && (
        <>
      {/* 0. Traces link card */}
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold text-foreground">Traces</h2>
        {phoenixUrlState.loading ? (
          <Skeleton className="h-12 w-full rounded-lg" />
        ) : phoenixUrlState.error ? (
          <div className="flex h-12 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-sm text-red-600">
            Could not check Phoenix status.
          </div>
        ) : (
          <TracesCard phoenix={phoenixUrlState.data} />
        )}
      </section>

      {/* 1. System Status */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">System Status</h2>
        {overviewState.loading || llmState.loading ? (
          <MetricCardSkeleton />
        ) : overviewState.error && llmState.error ? (
          <SectionErrorCard name="System Status" />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatusIndicator ok={ollamaOnline} label="Ollama" />
              <StatusIndicator ok={overviewState.data?.phoenix_running ?? false} label="Phoenix" />
              <StatusIndicator ok={overviewState.data?.langfuse_configured ?? false} label="Langfuse" />
              <ModelBadge model={activeModel} />
            </div>
            {overviewState.data && (
              <div className="grid grid-cols-3 gap-3">
                <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
                  <span className="text-lg font-bold text-foreground">{overviewState.data.total_documents}</span>
                  <span className="text-xs text-muted-foreground">Documents</span>
                </div>
                <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
                  <span className="text-lg font-bold text-foreground">{overviewState.data.total_chunks}</span>
                  <span className="text-xs text-muted-foreground">Chunks</span>
                </div>
                <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
                  <span className="text-lg font-bold text-foreground">{overviewState.data.qa_calls_today}</span>
                  <span className="text-xs text-muted-foreground">QA calls today</span>
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* 2. RAG Quality */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">RAG Quality</h2>
        {evalRunsState.loading ? (
          <SectionSkeleton rows={4} />
        ) : evalRunsState.error ? (
          <SectionErrorCard name="RAG Quality" />
        ) : (
          <RAGQualityChart evalRuns={evalRunsState.data} />
        )}
      </section>

      {/* 3. HR@5 Over Time */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Retrieval Quality Over Time</h2>
        <p className="text-xs text-muted-foreground">HR@5 per dataset across eval runs. Dashed line = 0.60 threshold.</p>
        {evalHistState.loading ? (
          <SectionSkeleton rows={3} />
        ) : evalHistState.error ? (
          <SectionErrorCard name="Retrieval Quality Over Time" />
        ) : (
          <EvalHistorySparkline history={evalHistState.data} />
        )}
      </section>

      <section className="flex flex-col gap-3">
        {evalHistState.loading ? (
          <SectionSkeleton rows={3} />
        ) : evalHistState.error ? (
          <SectionErrorCard name="Eval Trends" />
        ) : (
          <EvalTrendsPanel history={evalHistState.data} />
        )}
      </section>

      {/* 4. Model Usage */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Model Usage</h2>
        {modelUsageState.loading ? (
          <SectionSkeleton rows={3} />
        ) : modelUsageState.error ? (
          <SectionErrorCard name="Model Usage" />
        ) : (
          <ModelUsageSection modelUsage={modelUsageState.data} />
        )}
      </section>

      {/* 5. Ingestion Queue */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Ingestion Queue</h2>
        {docsState.loading ? (
          <SectionSkeleton rows={2} />
        ) : docsState.error ? (
          <SectionErrorCard name="Ingestion Queue" />
        ) : ingestingDocs.length === 0 ? (
          <EmptyState message="No documents currently ingesting." />
        ) : (
          <div className="flex flex-col gap-1 rounded-lg border border-border">
            {ingestingDocs.map((doc, i) => (
              <div
                key={doc.id}
                className={`flex items-center justify-between px-4 py-2 text-sm ${
                  i > 0 ? "border-t border-border" : ""
                }`}
              >
                <span className="font-medium text-foreground">{doc.title}</span>
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                  {doc.stage}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 6. Recent Traces */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Recent Traces</h2>
        {tracesState.loading ? (
          <SectionSkeleton rows={5} />
        ) : tracesState.error ? (
          <SectionErrorCard name="Recent Traces" />
        ) : (
          <>
            {tracesState.data.message && (
              <p className="text-sm text-muted-foreground">{tracesState.data.message}</p>
            )}
            {tracesState.data.traces.length === 0 ? (
              <EmptyState message="No traces available." />
            ) : (
              <div className="overflow-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-secondary/50">
                      <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Timestamp</th>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Operation</th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Duration</th>
                      <th className="px-4 py-2 text-center text-xs font-semibold text-muted-foreground">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tracesState.data.traces.map((t) => (
                      <tr
                        key={t.span_id || `${t.trace_id}-${t.start_time}`}
                        onClick={() => setSelectedTrace(t)}
                        className="cursor-pointer border-b border-border last:border-0 hover:bg-accent"
                      >
                        <td className="px-4 py-2 text-xs text-muted-foreground">
                          {t.start_time ? new Date(t.start_time).toLocaleTimeString() : "—"}
                        </td>
                        <td className="px-4 py-2 font-medium text-foreground">{t.operation_name}</td>
                        <td className="px-4 py-2 text-right text-muted-foreground">
                          {t.duration_ms.toFixed(1)} ms
                        </td>
                        <td className="px-4 py-2 text-center">
                          <StatusBadge status={t.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      {/* 7a. RAGAS Eval Results — from /evals/results */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">RAGAS Eval Results</h2>
        <p className="text-xs text-muted-foreground">
          Latest result per dataset. Green = meets threshold, amber = close, grey = below. Click Run Eval to trigger a background eval run.
        </p>
        <EvalPanel />
      </section>

      {/* 7b. Eval Runs (legacy /monitoring/evals) */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Eval Runs</h2>
        {evalRunsState.loading ? (
          <SectionSkeleton rows={4} />
        ) : evalRunsState.error ? (
          <SectionErrorCard name="Eval Runs" />
        ) : evalRunsState.data.length === 0 ? (
          <EmptyState message="No evaluation runs yet. Run evals/run_eval.py to populate." />
        ) : (
          <div className="overflow-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/50">
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Dataset</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Run At</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">HR@5</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">MRR</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Faithfulness</th>
                </tr>
              </thead>
              <tbody>
                {evalRunsState.data.map((run) => {
                  const hr5 = run.hit_rate_5
                  const rowBg =
                    hr5 !== null && hr5 < 0.5
                      ? "bg-red-50 dark:bg-red-950/30"
                      : hr5 !== null && hr5 > 0.7
                        ? "bg-green-50 dark:bg-green-950/30"
                        : ""
                  return (
                    <tr key={run.id} className={`border-b border-border last:border-0 ${rowBg}`}>
                      <td className="px-4 py-2 font-medium text-foreground">{run.dataset_name}</td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">
                        {new Date(run.run_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {hr5 !== null ? hr5.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {run.mrr !== null ? run.mrr.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-foreground">
                        {run.faithfulness !== null ? run.faithfulness.toFixed(2) : "—"}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Trace detail panel */}
      {selectedTrace && (
        <TraceDetailPanel trace={selectedTrace} onClose={() => setSelectedTrace(null)} />
      )}
        </>
      )}
    </div>
  )
}
