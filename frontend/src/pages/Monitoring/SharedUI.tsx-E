// Small shared UI primitives for the Monitoring page: status pills,
// section error / empty / skeleton states, and the trace detail
// drawer. Each is pure presentation, no fetch or local state beyond
// what the trace drawer's onClose requires.

import { X as XIcon } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

import type { TraceItem } from "./types"

export function StatusBadge({ status }: { status: string }) {
  const isError = status === "error"
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        isError ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
      }`}
    >
      {isError ? "error" : "ok"}
    </span>
  )
}

export function StatusIndicator({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
        />
        <span className={`text-sm font-semibold ${ok ? "text-green-700" : "text-red-600"}`}>
          {ok ? "Online" : "Offline"}
        </span>
      </div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

export function ModelBadge({ model }: { model: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3">
      <span className="truncate text-sm font-semibold text-foreground">{model}</span>
      <span className="text-xs text-muted-foreground">Active Model</span>
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
    <div className="flex h-24 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-sm text-red-600">
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
  onClose,
}: {
  trace: TraceItem
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-lg flex-col bg-background shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="font-semibold text-foreground">Span Details</h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <XIcon size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <div className="mb-4 flex flex-col gap-1 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Operation</span>
              <span className="font-medium text-foreground">{trace.operation_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Span ID</span>
              <span className="font-mono text-xs text-foreground">{trace.span_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Trace ID</span>
              <span className="font-mono text-xs text-foreground">{trace.trace_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Duration</span>
              <span className="text-foreground">{trace.duration_ms.toFixed(1)} ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Status</span>
              <StatusBadge status={trace.status} />
            </div>
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
