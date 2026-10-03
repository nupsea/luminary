// One-click install for an optional component, with live progress.
//
// Replaces the shell instructions the UI used to print (`ollama serve`,
// `ollama pull llama3.2`). A desktop user has no terminal, and the app owns the
// model server, so telling them to run a command was never the right fix.

import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Download, Loader2, RotateCw } from "lucide-react"

import { ChatModelChoice } from "@/components/setup/ChatModelChoice"
import { ReportProblem } from "@/components/setup/ReportProblem"
import { useComponents } from "@/hooks/useSetup"
import { formatBytes, installComponent, refreshModelState } from "@/lib/setupApi"
import { cn } from "@/lib/utils"

interface Props {
  componentId: string
  className?: string
  onInstalled?: () => void
  /** False where the surrounding screen already offers one report for everything. */
  reportable?: boolean
}

export function InstallComponentButton({
  componentId,
  className,
  onInstalled,
  reportable = true,
}: Props) {
  const queryClient = useQueryClient()
  const { data: components } = useComponents()
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [choosing, setChoosing] = useState(false)

  const component = components?.find((c) => c.id === componentId)
  if (!component || component.installed || !component.offered) return null

  // A tool has no installer; the advice shown with the component says how to add it.
  if (component.installable === false) {
    return (
      <span className={cn("inline-flex flex-col gap-1", className)}>
        <button
          type="button"
          onClick={() => void queryClient.invalidateQueries({ queryKey: ["setup"] })}
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
        >
          <RotateCw size={13} /> Check again
        </button>
      </span>
    )
  }

  // More than one model fits: the user picks, never the app.
  if (component.choices && component.choices.length > 1) {
    return (
      <span className={cn("inline-flex flex-col gap-1.5", className)}>
        <button
          type="button"
          onClick={() => setChoosing((open) => !open)}
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
        >
          <Download size={13} /> Choose a {component.label.toLowerCase()}
        </button>
        {choosing && <ChatModelChoice choices={component.choices} />}
      </span>
    )
  }

  async function run() {
    setBusy(true)
    setError(null)
    let failed = false
    try {
      await installComponent(componentId, (event) => {
        if (event.state === "failed") {
          failed = true
          setError(event.detail ?? "Install failed")
          return
        }
        if (event.total_bytes) {
          setProgress(
            `${formatBytes(event.completed_bytes ?? 0)} of ${formatBytes(event.total_bytes)}`,
          )
        } else if (event.detail) {
          setProgress(event.detail)
        }
      })
      // A model install can switch the chat model and turn the host verdict.
      await refreshModelState(queryClient)
      if (!failed) onInstalled?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Install failed")
    } finally {
      setBusy(false)
      setProgress(null)
    }
  }

  return (
    <span className={cn("inline-flex flex-col gap-1", className)}>
      <button
        type="button"
        onClick={() => void run()}
        disabled={busy}
        className="inline-flex items-center gap-1.5 self-start rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-60"
      >
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
        {busy ? "Installing" : error ? "Try again" : `Install ${component.label.toLowerCase()}`}
        {!busy && (
          <span className="text-muted-foreground">({formatBytes(component.size_bytes)})</span>
        )}
      </button>
      {progress && <span className="text-xs tabular-nums text-muted-foreground">{progress}</span>}
      {error && (
        <>
          <span className="text-xs text-muted-foreground">{error}</span>
          {reportable && (
            <ReportProblem problem={`${component.label} download failed`} detail={error} />
          )}
        </>
      )}
    </span>
  )
}
