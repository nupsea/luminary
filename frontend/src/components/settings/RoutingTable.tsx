// Where each unit of work actually runs, read from GET /settings/llm/routing.
//
// The mode cards above this say "Cloud for chat; Ollama for background tasks",
// which is a promise. This is the same claim as a list a user can check: every
// row names the model that will serve it, and the rows that cannot move say why
// they cannot. Nothing here is written down in this file -- a hardcoded table
// would keep reassuring the reader after a route moved.
//
// It renders the SAVED mode, not the radio button the user is hovering. Showing
// a routing report for a mode nobody has committed to would be the same lie in
// the other direction.

import { useQuery } from "@tanstack/react-query"
import { Cloud, HardDrive, Lock } from "lucide-react"

import { egressSummary, fetchRouting, type WorkRoutingItem } from "@/lib/llmRouting"
import { cn } from "@/lib/utils"

function EngineChip({ item }: { item: WorkRoutingItem }) {
  const Icon = item.on_device ? (item.routable ? HardDrive : Lock) : Cloud
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
        item.on_device
          ? "bg-green-500/10 text-green-700 dark:text-green-400"
          : "bg-blue-500/10 text-blue-700 dark:text-blue-400",
      )}
    >
      <Icon size={11} />
      {item.on_device ? "This machine" : "Cloud"}
    </span>
  )
}

function Row({ item }: { item: WorkRoutingItem }) {
  return (
    <li className="flex flex-col gap-1 border-b border-border py-2.5 last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs font-medium text-foreground">{item.label}</span>
        <EngineChip item={item} />
      </div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[11px] text-muted-foreground break-all">
          {/* A null model is not "none" -- there is no model in this row at all. */}
          {item.model ?? "no model involved"}
        </span>
        {!item.routable && (
          <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground/70">
            always local
          </span>
        )}
      </div>
      {item.fallback_reason && (
        <p className="text-[11px] text-amber-700 dark:text-amber-400">
          Falling back: {item.fallback_reason}
        </p>
      )}
    </li>
  )
}

export function RoutingTable() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["llm-routing"],
    queryFn: fetchRouting,
  })

  if (isLoading) {
    return <div className="h-56 animate-pulse rounded-md bg-muted" />
  }

  if (isError || !data) {
    return (
      <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
        Could not read where your work is running.{" "}
        <button type="button" onClick={() => void refetch()} className="underline hover:text-foreground">
          Try again
        </button>
      </div>
    )
  }

  if (data.work.length === 0) {
    return (
      <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
        No work routing to show yet.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border p-3">
      <ul className="mb-3">
        {data.work.map((item) => (
          <Row key={item.id} item={item} />
        ))}
      </ul>
      <p className="text-[11px] leading-relaxed text-muted-foreground">{egressSummary(data)}</p>
    </div>
  )
}
