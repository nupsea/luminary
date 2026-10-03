// The chat model is the user's choice. Luminary recommends one for this computer and
// states what each costs; it never downloads one the user did not pick.

import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, Download, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { ReportProblem } from "@/components/setup/ReportProblem"
import { apiPatch } from "@/lib/apiClient"
import { formatBytes, installOrThrow, type ChatModelChoice as Choice } from "@/lib/setupApi"
import { cn } from "@/lib/utils"

function bare(model: string): string {
  return model.replace(/^ollama\//, "")
}

export function ChatModelChoice({ choices }: { choices: Choice[] }) {
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState<string | null>(null)
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState<{ model: string; detail: string } | null>(null)

  async function use(choice: Choice) {
    setBusy(choice.model)
    setError(null)
    try {
      if (!choice.installed) {
        await installOrThrow(`model:${bare(choice.model)}`, (event) => {
          if (event.total_bytes) {
            setProgress(
              `${formatBytes(event.completed_bytes ?? 0)} of ${formatBytes(event.total_bytes)}`,
            )
          } else if (event.detail) {
            setProgress(event.detail)
          }
        })
      }
      // Switched only after the download completes, so a failed one leaves the old model.
      await apiPatch("/settings/llm", { local_chat_model: choice.model })
      await queryClient.invalidateQueries({ queryKey: ["setup"] })
      await queryClient.invalidateQueries({ queryKey: ["llm-settings"] })
      await queryClient.invalidateQueries({ queryKey: ["host-support"] })
      toast.success(`Now using ${bare(choice.model)} for chat and flashcards`)
    } catch (e) {
      setError({ model: choice.model, detail: e instanceof Error ? e.message : "Install failed" })
    } finally {
      setBusy(null)
      setProgress(null)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {choices.map((choice) => {
        const running = busy === choice.model
        const failed = error?.model === choice.model ? error.detail : null
        return (
          <div
            key={choice.model}
            className={cn(
              "flex flex-col gap-1.5 rounded-md border p-2.5",
              choice.selected ? "border-primary bg-primary/5" : "border-border",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium text-foreground">
                {bare(choice.model)}
              </span>
              {choice.recommended && (
                <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                  Recommended for this computer
                </span>
              )}
            </div>
            <p className="text-xs text-foreground/80">{choice.trade_off}</p>
            <p className="text-xs text-muted-foreground">
              {formatBytes(choice.size_bytes)} to download, and about as much memory while it
              runs.
            </p>
            {choice.selected && choice.installed ? (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-500">
                <Check size={12} /> In use
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
                  : choice.installed
                    ? "Use this model"
                    : `Install and use (${formatBytes(choice.size_bytes)})`}
              </button>
            )}
            {failed && (
              <>
                <span className="text-xs text-muted-foreground">{failed}</span>
                <ReportProblem
                  problem={`Chat model ${bare(choice.model)} could not be installed`}
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
