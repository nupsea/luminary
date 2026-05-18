// Slide-up "Your study plan" panel above the chat input.

import { AlertTriangle, BookMarked, BookOpen, X } from "lucide-react"

import type { SessionPlanResponse } from "./types"

interface SessionPlanPanelProps {
  open: boolean
  onClose: () => void
  plan: SessionPlanResponse | undefined
  loading: boolean
  error: boolean
  onRetry: () => void
  onNavigate: (target: string) => void
}

export function SessionPlanPanel({ open, onClose, plan, loading, error, onRetry, onNavigate }: SessionPlanPanelProps) {
  return (
    <div
      className={`border-t border-border bg-background transition-[max-height,opacity] duration-300 ease-in-out overflow-hidden ${open ? "max-h-96 opacity-100" : "max-h-0 opacity-0 pointer-events-none"}`}
    >
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <span className="text-sm font-medium">
          Your study plan ({plan?.total_minutes ?? 20} min)
        </span>
        <button
          onClick={onClose}
          className="rounded p-0.5 text-muted-foreground hover:bg-accent"
          aria-label="Close plan panel"
        >
          <X size={14} />
        </button>
      </div>
      <div className="px-6 py-3">
        {loading ? (
          <div className="flex flex-col gap-2">
            <div className="h-10 animate-pulse rounded bg-muted" />
            <div className="h-10 animate-pulse rounded bg-muted" />
            <div className="h-10 animate-pulse rounded bg-muted" />
          </div>
        ) : error ? (
          <div className="flex items-center gap-3 text-sm text-destructive">
            <span>Could not load your study plan. Try again.</span>
            <button
              onClick={onRetry}
              className="rounded border border-destructive px-2 py-0.5 text-xs hover:bg-destructive/10"
            >
              Retry
            </button>
          </div>
        ) : !plan || plan.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No study tasks found. You are all caught up!</p>
        ) : (
          <div className="flex flex-col gap-2">
            {plan.items.map((item, idx) => (
              <div key={idx} className="flex items-center justify-between rounded-md border border-border px-3 py-2">
                <div className="flex items-center gap-2">
                  {item.type === "review" ? (
                    <BookOpen size={14} className="shrink-0 text-blue-500" />
                  ) : item.type === "gap" ? (
                    <AlertTriangle size={14} className="shrink-0 text-amber-500" />
                  ) : (
                    <BookMarked size={14} className="shrink-0 text-green-500" />
                  )}
                  <span className="text-sm">{item.title}</span>
                  <span className="rounded bg-muted px-1 text-xs text-muted-foreground">{item.minutes} min</span>
                </div>
                <button
                  onClick={() => onNavigate(item.action_target)}
                  className="ml-3 shrink-0 rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                >
                  {item.action_label}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
