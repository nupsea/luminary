// One-click install for an optional component, with live progress.
//
// Replaces the shell instructions the UI used to print (`ollama serve`,
// `ollama pull llama3.2`). A desktop user has no terminal, and the app owns the
// model server, so telling them to run a command was never the right fix.

import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Download, Loader2 } from "lucide-react"

import { useComponents } from "@/hooks/useSetup"
import { formatBytes, installComponent } from "@/lib/setupApi"
import { cn } from "@/lib/utils"

interface Props {
  componentId: string
  className?: string
  onInstalled?: () => void
}

export function InstallComponentButton({ componentId, className, onInstalled }: Props) {
  const queryClient = useQueryClient()
  const { data: components } = useComponents()
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const component = components?.find((c) => c.id === componentId)
  if (!component || component.installed) return null

  async function run() {
    setBusy(true)
    setError(null)
    try {
      await installComponent(componentId, (event) => {
        if (event.state === "failed") {
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
      await queryClient.invalidateQueries({ queryKey: ["setup"] })
      onInstalled?.()
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
        {busy ? "Installing" : `Install ${component.label.toLowerCase()}`}
        {!busy && (
          <span className="text-muted-foreground">({formatBytes(component.size_bytes)})</span>
        )}
      </button>
      {progress && <span className="text-xs tabular-nums text-muted-foreground">{progress}</span>}
      {error && <span className="text-xs text-muted-foreground">{error}</span>}
    </span>
  )
}
