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
import { AlertTriangle, Check, Loader2 } from "lucide-react"

import { LuminaryGlyph } from "@/components/icons/LuminaryGlyph"
import { useStartupStatus } from "@/hooks/useSetup"
import { formatBytes, type StartupPhase } from "@/lib/setupApi"
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

export function SetupGate({ children }: { children: ReactNode }) {
  const { data, isError } = useStartupStatus()
  const [dismissed, setDismissed] = useState(false)

  // Hold only while the app genuinely cannot be used, or while first-run
  // downloads are actively moving. A settled install that is merely missing an
  // optional model is not blocked here -- the banner offers to install it, and
  // trapping the user behind a setup screen they cannot clear would be worse
  // than the error box this replaced.
  const blocking = !data ? isError : !data.usable || data.status === "provisioning"
  if (!blocking || (dismissed && data?.usable)) return <>{children}</>

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
          {starting ? "Starting up" : "Setting up your library"}
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {starting
            ? "This takes a moment on first launch."
            : "Luminary is downloading the models it runs on. This happens once, and everything stays on this machine."}
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

        {usable && (
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="mt-6 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Start exploring while this finishes
          </button>
        )}
      </div>
    </div>
  )
}
