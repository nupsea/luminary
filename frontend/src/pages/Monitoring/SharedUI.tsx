// Small shared UI primitives for the Monitoring page: status pills,
// section error / empty / skeleton states, span-kind chips, and the
// trace detail drawer. Each is pure presentation.

import { Component, type ReactNode } from "react"

import { ExternalLink, X as XIcon } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

import { logger } from "@/lib/logger"

import type { TraceItem } from "./types"

// A rendering bug in one panel must degrade that panel, not unmount
// the page (invariant I-10: no blank panels).
export class PanelErrorBoundary extends Component<
  { name: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    logger.warn("[Monitoring] panel crashed", this.props.name, error)
  }

  render() {
    if (this.state.failed) return <SectionErrorCard name={this.props.name} />
    return this.props.children
  }
}

export function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "error"
      ? "bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-400"
      : status === "ok"
        ? "bg-green-100 text-green-700 dark:bg-green-950/60 dark:text-green-400"
        : "bg-secondary text-muted-foreground"
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status || "unset"}
    </span>
  )
}

const KIND_COLORS: Record<string, string> = {
  CHAIN: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-400",
  LLM: "bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-400",
  RETRIEVER: "bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-400",
  EMBEDDING: "bg-teal-100 text-teal-700 dark:bg-teal-950/60 dark:text-teal-400",
  TOOL: "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-400",
  AGENT: "bg-pink-100 text-pink-700 dark:bg-pink-950/60 dark:text-pink-400",
}

export function KindChip({ kind }: { kind: string }) {
  const cls = KIND_COLORS[kind] ?? "bg-secondary text-muted-foreground"
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide ${cls}`}>
      {kind}
    </span>
  )
}

export type PillState = "online" | "offline" | "disabled"

export function StatusPill({ state, label, detail }: { state: PillState; label: string; detail?: string }) {
  const dot =
    state === "online" ? "bg-green-500" : state === "offline" ? "bg-red-500" : "bg-gray-400"
  const text =
    state === "online"
      ? "text-green-700 dark:text-green-400"
      : state === "offline"
        ? "text-red-600 dark:text-red-400"
        : "text-muted-foreground"
  const caption = state === "online" ? "Online" : state === "offline" ? "Offline" : "Disabled"
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3" title={detail}>
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${dot}`} />
        <span className={`text-sm font-semibold ${text}`}>{caption}</span>
      </div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

export function StatCard({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card px-4 py-3">
      <span className="text-lg font-bold text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
      {message}
    </div>
  )
}

export function SectionErrorCard({ name }: { name: string }) {
  return (
    <div className="flex h-24 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-sm text-red-600 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
      Could not load {name}
    </div>
  )
}

export function SectionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

export function MetricCardSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-16 w-full rounded-lg" />
      ))}
    </div>
  )
}

export function TraceDetailPanel({
  trace,
  phoenixUrl,
  onClose,
}: {
  trace: TraceItem
  phoenixUrl?: string
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-lg flex-col bg-background shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="font-semibold text-foreground">Span Details</h3>
          <div className="flex items-center gap-2">
            {phoenixUrl && (
              <a
                href={phoenixUrl}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <ExternalLink size={12} />
                Open in Phoenix
              </a>
            )}
            <button
              onClick={onClose}
              className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <XIcon size={16} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <div className="mb-4 flex flex-col gap-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Operation</span>
              <span className="font-medium text-foreground">{trace.operation_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Kind</span>
              <KindChip kind={trace.span_kind ?? "UNKNOWN"} />
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Span ID</span>
              <span className="font-mono text-xs text-foreground">{trace.span_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Trace ID</span>
              <span className="font-mono text-xs text-foreground">{trace.trace_id}</span>
            </div>
            {trace.parent_id && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Parent span</span>
                <span className="font-mono text-xs text-foreground">{trace.parent_id}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-muted-foreground">Duration</span>
              <span className="text-foreground">{trace.duration_ms.toFixed(1)} ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <StatusBadge status={trace.status} />
            </div>
            {trace.status_message ? (
              <div className="flex justify-between gap-4">
                <span className="shrink-0 text-muted-foreground">Message</span>
                <span className="text-right text-xs text-red-600 dark:text-red-400">
                  {trace.status_message}
                </span>
              </div>
            ) : null}
            <div className="flex justify-between">
              <span className="text-muted-foreground">Start time</span>
              <span className="text-foreground">
                {trace.start_time ? new Date(trace.start_time).toLocaleString() : "—"}
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <p className="text-xs font-semibold text-muted-foreground">Attributes</p>
            <pre className="overflow-auto rounded bg-secondary p-3 text-xs text-foreground">
              {JSON.stringify(trace.attributes, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  )
}
