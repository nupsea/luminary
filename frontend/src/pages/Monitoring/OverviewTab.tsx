// Overview tab: system status pills (tri-state -- a deliberately disabled
// integration renders neutral, not as an alarming "Offline"), corpus
// counts, span-derived performance metrics, QA activity trend, and the
// ingestion queue. Model configuration lives in Settings; per-model call
// counts live on the Admin page -- neither is repeated here.

import { QAActivityChart } from "./Charts"
import {
  EmptyState,
  KindChip,
  MetricCardSkeleton,
  SectionErrorCard,
  SectionSkeleton,
  StatCard,
  StatusPill,
} from "./SharedUI"
import { fetchDocuments, fetchLLMSettings, fetchMetrics, fetchOverview } from "./api"
import type { Document, LLMSettings, MonitoringMetrics, MonitoringOverview } from "./types"
import { useSection } from "./useSection"
import { formatCount, formatDuration } from "./utils"

export function OverviewTab() {
  const overview = useSection<MonitoringOverview | null>("System Status", fetchOverview, null, 30_000)
  const llm = useSection<LLMSettings | null>("LLM Settings", fetchLLMSettings, null)
  const metrics = useSection<MonitoringMetrics | null>("Performance", fetchMetrics, null, 30_000)
  const docs = useSection<Document[]>("Ingestion Queue", fetchDocuments, [], 15_000)

  // ollama_reachable is a real health probe; processing_mode alone only
  // says which mode is configured.
  const ollamaState =
    llm.data == null
      ? "disabled"
      : (llm.data.ollama_reachable ?? llm.data.processing_mode === "local")
        ? "online"
        : "offline"
  const phoenixState = !overview.data?.phoenix_configured
    ? "disabled"
    : overview.data.phoenix_running
      ? "online"
      : "offline"
  const langfuseState = overview.data?.langfuse_configured ? "online" : "disabled"
  const ingestingDocs = docs.data.filter((d) => d.stage !== "complete")
  const m = metrics.data

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">System Status</h2>
        {overview.loading || llm.loading ? (
          <MetricCardSkeleton />
        ) : overview.error && llm.error ? (
          <SectionErrorCard name="System Status" />
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3">
              <StatusPill state={ollamaState} label="Ollama" />
              <StatusPill
                state={phoenixState}
                label="Phoenix Tracing"
                detail={
                  phoenixState === "disabled"
                    ? "Set PHOENIX_ENABLED=true in backend/.env to enable tracing"
                    : undefined
                }
              />
              <StatusPill
                state={langfuseState}
                label="Langfuse"
                detail={
                  langfuseState === "disabled" ? "No LANGFUSE_PUBLIC_KEY configured" : undefined
                }
              />
            </div>
            {overview.data && (
              <div className="grid grid-cols-3 gap-3">
                <StatCard value={overview.data.total_documents} label="Documents" />
                <StatCard value={overview.data.total_chunks} label="Chunks" />
                <StatCard value={overview.data.qa_calls_today} label="QA calls today" />
              </div>
            )}
          </>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Performance</h2>
        <p className="text-xs text-muted-foreground">
          Computed from the most recent traced operations (up to 200 spans).
        </p>
        {metrics.loading ? (
          <MetricCardSkeleton />
        ) : metrics.error ? (
          <SectionErrorCard name="Performance" />
        ) : !m ? null : !m.phoenix_available ? (
          <EmptyState message="Latency, error, and token metrics need tracing. Set PHOENIX_ENABLED=true in backend/.env and restart the backend." />
        ) : m.spans_sampled === 0 ? (
          <EmptyState message="No traced operations yet. Ask a question or ingest a document." />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard
                value={m.latency_p50_ms != null ? formatDuration(m.latency_p50_ms) : "—"}
                label="Latency p50"
              />
              <StatCard
                value={m.latency_p95_ms != null ? formatDuration(m.latency_p95_ms) : "—"}
                label="Latency p95"
              />
              <StatCard
                value={m.error_rate != null ? `${(m.error_rate * 100).toFixed(1)}%` : "—"}
                label={`Error rate (${m.error_count} of ${m.spans_sampled} spans)`}
              />
              <StatCard
                value={`${formatCount(m.llm_prompt_tokens)} in / ${formatCount(m.llm_completion_tokens)} out`}
                label={`LLM tokens (${m.llm_calls} calls)`}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>Spans by kind:</span>
              {Object.entries(m.spans_by_kind).map(([kind, count]) => (
                <span key={kind} className="flex items-center gap-1">
                  <KindChip kind={kind} />
                  <span className="text-foreground">{count}</span>
                </span>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">QA Activity (7 days)</h2>
        {metrics.loading ? (
          <SectionSkeleton rows={2} />
        ) : metrics.error ? (
          <SectionErrorCard name="QA Activity" />
        ) : m ? (
          <QAActivityChart daily={m.qa_daily} />
        ) : null}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-foreground">Ingestion Queue</h2>
        {docs.loading ? (
          <SectionSkeleton rows={2} />
        ) : docs.error ? (
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
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-950/60 dark:text-amber-400">
                  {doc.stage}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
