// Dictation can use a larger Whisper model than audio import: an answer lasts seconds,
// and the small import model mishears accents. Choosing one installs Speech to text too.

import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, Download, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { ReportProblem } from "@/components/setup/ReportProblem"
import {
  formatBytes,
  installOrThrow,
  refreshModelState,
  type Component,
  type DictationModelChoice as Choice,
} from "@/lib/setupApi"
import { cn } from "@/lib/utils"

export function DictationModelChoice({
  transcription,
  onInstalled,
}: {
  transcription: Component
  onInstalled?: () => void
}) {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState<string | null>(null)
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<{ model: string; detail: string } | null>(null)
  const choices = transcription.dictation_choices ?? []

  async function use(choice: Choice) {
    setBusy(choice.model)
    setError(null)
    try {
      await installOrThrow(`dictation:${choice.model}`, (event) => {
        if (event.total_bytes) {
          setProgress(
            `${formatBytes(event.completed_bytes ?? 0)} of ${formatBytes(event.total_bytes)}`,
          )
        } else if (event.detail) {
          setProgress(event.detail)
        }
      })
      await refreshModelState(queryClient)
      toast.success(`Dictation now uses Whisper ${choice.model}`)
      onInstalled?.()
    } catch (e) {
      setError({ model: choice.model, detail: e instanceof Error ? e.message : "Install failed" })
    } finally {
      setBusy(null)
      setProgress(null)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium text-foreground">Dictation model</span>
      {choices.map((choice) => {
        const running = busy === choice.model
        const failed = error?.model === choice.model ? error.detail : null
        const download =
          (choice.installed ? 0 : choice.size_bytes) +
          (transcription.installed ? 0 : transcription.size_bytes)
        const active = choice.selected && transcription.installed
        return (
          <div
            key={choice.model}
            className={cn(
              "flex flex-col gap-1.5 rounded-md border p-2.5",
              active ? "border-primary bg-primary/5" : "border-border",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium text-foreground">{choice.model}</span>
              {choice.recommended && (
                <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                  Recommended
                </span>
              )}
            </div>
            <p className="text-xs text-foreground/80">{choice.trade_off}</p>
            {active && choice.installed ? (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-500">
                <Check size={12} /> Used for dictation
              </span>
            ) : (
              <button
                type="button"
                onClick={() => void use(choice)}
                disabled={busy !== null}
                className="inline-flex items-center gap-1.5 self-start rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-60"
              >
                {running ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                {running
                  ? (progress ?? "Installing")
                  : download === 0
                    ? "Use for dictation"
                    : `Install and use (${formatBytes(download)})`}
              </button>
            )}
            {failed && (
              <>
                <span className="text-xs text-muted-foreground">{failed}</span>
                <ReportProblem
                  problem={`Dictation model ${choice.model} could not be installed`}
                  detail={failed}
                />
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
