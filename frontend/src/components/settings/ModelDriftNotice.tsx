// Tells the user when the host is running a different model than the one
// configured, and lets them adopt the resolved model without losing the
// download-before-pin-flip guarantee (docs/roadmap.md #5).
//
// narrowed_defaults (GET /settings/models) has carried this signal since
// model_router.narrowed_defaults() shipped; nothing rendered it. Framed as
// fit, never quality: the resolved model is not "better," it is what this
// machine can actually hold or resolve to.

import { useState } from "react"
import { AlertTriangle, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { installComponent, type InstallProgress } from "@/lib/setupApi"
import { cn } from "@/lib/utils"

export interface ModelDrift {
  configured: string
  resolved: string
  reason: string
}

export type ModelRole = "chat" | "vision"

const ROLE_LABEL: Record<ModelRole, string> = { chat: "chat model", vision: "vision model" }
const ROLE_FIELD: Record<ModelRole, "local_chat_model" | "vision_model"> = {
  chat: "local_chat_model",
  vision: "vision_model",
}

function bare(model: string): string {
  return model.replace(/^ollama\//, "")
}

interface Props {
  narrowedDefaults: Partial<Record<ModelRole, ModelDrift>>
  availableLocalModels: string[]
  onSave: (updates: { local_chat_model?: string; vision_model?: string }) => Promise<void>
}

export function ModelDriftNotice({ narrowedDefaults, availableLocalModels, onSave }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [busyRole, setBusyRole] = useState<ModelRole | null>(null)
  const [progress, setProgress] = useState<string | null>(null)

  const key = (role: ModelRole, d: ModelDrift) => `${role}:${d.configured}:${d.resolved}`
  const roles = (Object.keys(narrowedDefaults) as ModelRole[]).filter((role) => {
    const d = narrowedDefaults[role]
    return !!d && !dismissed.has(key(role, d))
  })
  if (roles.length === 0) return null

  async function switchTo(role: ModelRole, drift: ModelDrift) {
    setBusyRole(role)
    setProgress(null)
    try {
      if (!availableLocalModels.includes(drift.resolved)) {
        let failure: string | null = null
        await installComponent(`model:${bare(drift.resolved)}`, (event: InstallProgress) => {
          if (event.state === "failed") {
            failure = event.detail ?? "Install failed"
            return
          }
          if (event.total_bytes) {
            setProgress(`${(((event.completed_bytes ?? 0) / event.total_bytes) * 100).toFixed(0)}%`)
          } else if (event.detail) {
            setProgress(event.detail)
          }
        })
        // The stream can end "successfully" after a mid-stream failure event
        // -- installComponent only throws on an HTTP-level error -- so the
        // pin must not flip unless the last thing seen was a real failure.
        if (failure) throw new Error(failure)
      }
      await onSave({ [ROLE_FIELD[role]]: drift.resolved })
      toast.success(`Now using ${bare(drift.resolved)} for the ${ROLE_LABEL[role]}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : `Couldn't switch the ${ROLE_LABEL[role]}`)
    } finally {
      setBusyRole(null)
      setProgress(null)
    }
  }

  return (
    <div className="space-y-2">
      {roles.map((role) => {
        const drift = narrowedDefaults[role]
        if (!drift) return null
        const busy = busyRole === role
        return (
          <div
            key={role}
            className="flex flex-col gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <p className="text-xs">
                Running <code className="font-mono">{bare(drift.resolved)}</code> for the{" "}
                {ROLE_LABEL[role]} instead of the configured{" "}
                <code className="font-mono">{bare(drift.configured)}</code> — {drift.reason}.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => void switchTo(role, drift)}
                disabled={busy}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border border-amber-400 bg-white px-2.5 py-1 text-xs font-medium text-amber-900",
                  "hover:bg-amber-100 disabled:opacity-60 dark:border-amber-800 dark:bg-transparent dark:text-amber-200",
                )}
              >
                {busy && <Loader2 size={12} className="animate-spin" />}
                {busy ? (progress ?? "Switching…") : `Switch to ${bare(drift.resolved)}`}
              </button>
              <button
                onClick={() => setDismissed((prev) => new Set(prev).add(key(role, drift)))}
                disabled={busy}
                className="text-xs text-amber-800/70 hover:text-amber-900 disabled:opacity-60 dark:text-amber-300/70 dark:hover:text-amber-200"
              >
                Dismiss
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
