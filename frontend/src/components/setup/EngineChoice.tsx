// The one question first run asks: answer here, or answer in the cloud.
//
// It is asked before "add a document" because it is the only setting that changes
// how the next five minutes feel, and because a stranger deciding whether to keep
// Luminary meets the local arm's time-to-first-token before anything else.
//
// **No invented numbers.** The local side quotes `local_probe_seconds` when the
// start-up probe measured this host and says nothing numeric when it did not --
// null is not "fast". The cloud side quotes nothing at all, because nothing has
// measured it on this machine yet; the receipt under the first answer supplies the
// real figure, which is the honest place for it.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Cloud, HardDrive, Loader2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { apiGet, apiPatch } from "@/lib/apiClient"
import { fetchRouting } from "@/lib/llmRouting"
import { cn } from "@/lib/utils"

interface LLMModeState {
  mode: "private" | "hybrid" | "cloud"
  has_openai_key: boolean
  has_anthropic_key: boolean
  has_google_key: boolean
}

const PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic" },
  { id: "gemini", label: "Google Gemini" },
] as const

export function EngineChoice({ onChosen }: { onChosen?: () => void }) {
  const queryClient = useQueryClient()
  const [pick, setPick] = useState<"private" | "hybrid" | null>(null)
  const [provider, setProvider] = useState<string>("anthropic")
  const [apiKey, setApiKey] = useState("")

  const { data: routing } = useQuery({ queryKey: ["llm-routing"], queryFn: fetchRouting })
  const { data: llm } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => apiGet<LLMModeState>("/settings/llm"),
  })

  const save = useMutation({
    mutationFn: async (mode: "private" | "hybrid") => {
      const updates: Record<string, string> = { mode }
      if (mode === "hybrid") {
        updates["provider"] = provider
        if (apiKey.trim()) {
          const field =
            provider === "openai"
              ? "openai_api_key"
              : provider === "anthropic"
                ? "anthropic_api_key"
                : "google_api_key"
          updates[field] = apiKey.trim()
        }
      }
      await apiPatch("/settings/llm", updates)
    },
    onSuccess: () => {
      setApiKey("")
      void queryClient.invalidateQueries({ queryKey: ["llm-settings"] })
      void queryClient.invalidateQueries({ queryKey: ["llm-routing"] })
      toast.success("Saved. You can change this any time in Settings.")
      onChosen?.()
    },
    onError: () => toast.error("Could not save that choice"),
  })

  const probe = routing?.local_probe_seconds ?? null
  const hasAnyKey =
    llm?.has_openai_key || llm?.has_anthropic_key || llm?.has_google_key || false

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-foreground">Where should answers come from?</h3>
        <p className="text-xs text-muted-foreground">
          Either way, your library, its index and your learner record stay on this machine.
          Only a question and the passages retrieved for it can ever leave.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => setPick("private")}
          aria-pressed={pick === "private"}
          className={cn(
            "flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
            pick === "private"
              ? "border-primary bg-primary/5"
              : "border-border hover:border-muted-foreground",
          )}
        >
          <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <HardDrive size={15} className="text-green-600" />
            Answer on this machine
          </span>
          <span className="text-xs text-muted-foreground">
            Nothing leaves, ever. No account, no key.
            {probe !== null
              ? ` This machine measured about ${probe.toFixed(0)}s for a local answer.`
              : " Local answers are slower than a cloud model."}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setPick("hybrid")}
          aria-pressed={pick === "hybrid"}
          className={cn(
            "flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
            pick === "hybrid"
              ? "border-primary bg-primary/5"
              : "border-border hover:border-muted-foreground",
          )}
        >
          <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Cloud size={15} className="text-blue-500" />
            Answer with your API key
          </span>
          <span className="text-xs text-muted-foreground">
            Faster and stronger answers. Reading, search, transcription and your
            learner record still run here. Every answer shows what it cost and what
            was sent.
          </span>
        </button>
      </div>

      {pick === "hybrid" && (
        <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
          <div className="flex gap-2">
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={hasAnyKey ? "A key is already saved" : "Paste an API key"}
              className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            Stored in your OS keychain, never in the library. Skip this and Luminary
            keeps working locally.
          </p>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={pick === null || save.isPending}
          onClick={() => pick && save.mutate(pick)}
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {save.isPending && <Loader2 size={14} className="animate-spin" />}
          Continue
        </button>
        <span className="text-[11px] text-muted-foreground">
          Changeable any time in Settings.
        </span>
      </div>
    </div>
  )
}
