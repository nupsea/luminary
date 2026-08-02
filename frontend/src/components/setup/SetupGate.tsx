// SetupGate — what a new install shows before it can do anything useful.
//
// A cold start downloads gigabytes of model weights. Without this the app
// renders its normal shell against a backend that is not answering, and the
// first thing a new user sees is an error box.
//
// The gate only holds while the library itself is unavailable. Once the
// database is up, browsing and adding documents work, so the user gets in and
// the remaining downloads move to a small status pill.

import { useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Check, Loader2, RotateCw } from "lucide-react"

import { LuminaryGlyph } from "@/components/icons/LuminaryGlyph"
import { useStartupStatus } from "@/hooks/useSetup"
import { formatBytes, retrySetup, type StartupPhase } from "@/lib/setupApi"
import { cn } from "@/lib/utils"

function PhaseRow({ phase }: { phase: StartupPhase }) {
  const done = phase.state === "ready" || phase.state === "skipped"
  const failed = phase.state === "failed"
  const busy = phase.state === "downloading" || phase.state === "loading"

  return (
    <li className="flex items-start gap-3 py-2">
      <span className="mt-0.5 shrink-0">
        {done ? (
          <Check size={16} className="text-emerald-600 dark:text-emerald-500" />
        ) : failed ? (
          <AlertTriangle size={16} className="text-amber-600 dark:text-amber-500" />
        ) : busy ? (
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        ) : (
          <span className="block h-4 w-4 rounded-full border border-border" />
        )}
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-3">
          <span className={cn("text-sm", done && "text-muted-foreground")}>{phase.label}</span>
          {phase.total_bytes > 0 && !done && (
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {formatBytes(phase.completed_bytes)} / {formatBytes(phase.total_bytes)}
            </span>
          )}
          {phase.state === "skipped" && (
            <span className="shrink-0 text-xs text-muted-foreground">Not needed</span>
          )}
        </span>

        {phase.percent !== null && !done && (
          <span className="mt-1.5 block h-1 w-full overflow-hidden rounded-full bg-border">
            <span
              className="block h-full rounded-full bg-primary transition-[width] duration-500"
              style={{ width: `${phase.percent}%` }}
            />
          </span>
        )}

        {failed && phase.detail && (
          <span className="mt-1 block text-xs text-muted-foreground">{phase.detail}</span>
        )}
      </span>
    </li>
  )
}

/**
 * Ambient progress for setup that is still running behind the app.
 *
 * Sits bottom-left, above the ingestion pills, and disappears on its own. It
 * exists so background downloads are visible without being in the way -- the
 * previous behaviour was either a blocking screen or silence.
 */
function SetupPill() {
  const { data } = useStartupStatus()
  if (!data || data.ready) return null

  const busy = data.phases.filter(
    (p) => p.state === "downloading" || p.state === "loading",
  )
  if (busy.length === 0) return null

  const current = busy[0]
  const pct = current.percent

  return (
    <div className="pointer-events-none fixed bottom-4 left-4 z-40 flex items-center gap-2.5 rounded-full border border-border bg-background/95 px-3 py-1.5 text-xs shadow-sm backdrop-blur">
      <Loader2 size={13} className="animate-spin text-muted-foreground" />
      <span className="text-foreground">{current.label}</span>
      {pct !== null && (
        <span className="tabular-nums text-muted-foreground">{Math.round(pct)}%</span>
      )}
      {busy.length > 1 && (
        <span className="text-muted-foreground">+{busy.length - 1}</span>
      )}
    </div>
  )
}

export function SetupGate({ children }: { children: ReactNode }) {
  const { data, isError } = useStartupStatus()
  const queryClient = useQueryClient()
  const [dismissed, setDismissed] = useState(false)
  const [retrying, setRetrying] = useState(false)

  const failedPhases = data?.phases.filter((p) => p.state === "failed") ?? []
  const hasFailure = failedPhases.length > 0
  // Distinguish "no network" from a genuine error: the wording and the odds of
  // a retry succeeding are completely different.
  const offline = failedPhases.some((p) => /internet|connect/i.test(p.detail))

  async function retry() {
    setRetrying(true)
    try {
      await retrySetup()
      await queryClient.invalidateQueries({ queryKey: ["setup"] })
    } finally {
      setRetrying(false)
    }
  }

  // Hold only for work the app cannot run without. Optional models -- the
  // entity extractor alone is 1.1GB -- finish in the background behind the
  // pill, because waiting minutes for something the library does not need is
  // the whole problem this screen was meant to solve.
  const blocking = !data ? isError : data.blocking
  if (!blocking || (dismissed && data?.usable)) {
    return (
      <>
        {children}
        <SetupPill />
      </>
    )
  }

  const usable = data?.usable ?? false
  const starting = !data || data.status === "starting"

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6 py-12">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2.5">
          <LuminaryGlyph className="h-6 w-6" />
          <h1 className="text-lg font-semibold tracking-tight">Luminary</h1>
        </div>

        <h2 className="text-xl font-medium tracking-tight">
          {starting ? "Warming up the engine" : "Getting your library ready"}
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {starting
            ? "A few seconds while everything comes online."
            : "Downloading what Luminary needs to read your documents. This happens once, and nothing leaves this machine."}
        </p>

        {data && (
          <ul className="mt-6 divide-y divide-border/60 border-y border-border/60">
            {data.phases.map((phase) => (
              <PhaseRow key={phase.key} phase={phase} />
            ))}
          </ul>
        )}

        {isError && !data && (
          <p className="mt-6 text-sm text-muted-foreground">
            Waiting for Luminary to respond. If this does not clear, quit and reopen the app.
          </p>
        )}

        {hasFailure && (
          <div className="mt-6 flex flex-col gap-2">
            <p className="text-sm text-muted-foreground">
              {offline
                ? "Luminary needs the internet once, to download the models it runs on."
                : "Some of the setup did not finish."}
            </p>
            <button
              type="button"
              onClick={() => void retry()}
              disabled={retrying}
              className="inline-flex items-center gap-1.5 self-start rounded-md border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:opacity-60"
            >
              {retrying ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />}
              {retrying ? "Retrying" : "Try again"}
            </button>
          </div>
        )}

        {usable && (
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="mt-6 block text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Continue without it
          </button>
        )}
      </div>
    </div>
  )
}
