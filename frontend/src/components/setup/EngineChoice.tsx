// The one question first run asks: Local, Hybrid or Cloud. All three are always
// offered and nothing is preselected on the user's behalf.
//
// No invented numbers: the local side quotes `local_probe_seconds` only when the
// start-up probe measured it; the cloud side quotes nothing.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Cloud, GitMerge, HardDrive, Loader2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { useHostVerdict } from "@/hooks/useHostVerdict"
import { apiGet, apiPatch } from "@/lib/apiClient"
import { PROVIDER_SETUP, providerSetup } from "@/lib/engineOffer"
import {
  ALWAYS_LOCAL,
  ENGINE_MODES,
  type EngineMode,
} from "@/lib/engineModes"
import { fetchRouting } from "@/lib/llmRouting"
import { cn } from "@/lib/utils"

interface LLMModeState {
  mode: EngineMode
  mode_chosen: boolean
  has_openai_key: boolean
  has_anthropic_key: boolean
  has_google_key: boolean
  // False in a container, where a saved key is written to the library rather
  // than an OS keychain. The sentence below has to follow it.
  keyring_available: boolean
}

const MODE_ICON = { private: HardDrive, hybrid: GitMerge, cloud: Cloud } as const

export function EngineChoice({ onChosen }: { onChosen?: () => void }) {
  const queryClient = useQueryClient()
  const [pick, setPick] = useState<EngineMode | null>(null)
  const [provider, setProvider] = useState<string>("anthropic")
  const [apiKey, setApiKey] = useState("")

  const { data: routing } = useQuery({ queryKey: ["llm-routing"], queryFn: fetchRouting })
  const { data: llm } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => apiGet<LLMModeState>("/settings/llm"),
  })
  const host = useHostVerdict()

  // A choice already made is shown as made; a default nobody chose is not.
  const selected = pick ?? (llm?.mode_chosen ? llm.mode : null)
  const selectedDef = ENGINE_MODES.find((m) => m.id === selected)

  const save = useMutation({
    mutationFn: async (mode: EngineMode) => {
      const updates: Record<string, string> = { mode }
      if (mode !== "private") {
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
  const setup = providerSetup(provider)
  const hasAnyKey =
    llm?.has_openai_key || llm?.has_anthropic_key || llm?.has_google_key || false
  const hostRefusesLocal = host?.supported === false

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-foreground">Where should models run?</h3>
        <p className="text-xs text-muted-foreground">{ALWAYS_LOCAL}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {ENGINE_MODES.map((mode) => {
          const Icon = MODE_ICON[mode.id]
          return (
            <button
              key={mode.id}
              type="button"
              onClick={() => setPick(mode.id)}
              aria-pressed={selected === mode.id}
              className={cn(
                "flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors",
                selected === mode.id
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-muted-foreground",
              )}
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Icon size={15} className="text-muted-foreground" />
                {mode.label}
              </span>
              <span className="text-xs text-muted-foreground">
                {mode.summary}
                {mode.id === "private" && !hostRefusesLocal && probe !== null
                  ? ` This machine measured about ${probe.toFixed(0)}s for a local answer.`
                  : ""}
              </span>
              <span className="text-[11px] text-muted-foreground">Sends: {mode.sends}</span>
              {hostRefusesLocal && (
                <span className="text-[11px] text-amber-700 dark:text-amber-400">
                  On this machine: {mode.onUnsupportedHost}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {selectedDef?.needsKey && (
        <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
          <div className="flex gap-2">
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
            >
              {PROVIDER_SETUP.map((p) => (
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
          {/* Where a key comes from is the step between wanting the fast arm and
              having it, and the question used to say nothing about it. */}
          <p className="text-[11px] text-muted-foreground">
            No key yet? Create one at{" "}
            <a
              href={setup?.consoleUrl ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-foreground"
            >
              {setup?.consoleLabel}
            </a>
            , then paste it above.
          </p>
          <p className="text-[11px] text-muted-foreground">
            {llm?.keyring_available === false
              ? "This install has no OS keychain, so the key is saved in your library database. Set it in the environment instead if that matters to you."
              : "Stored in your OS keychain, never in the library."}
          </p>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={selected === null || save.isPending}
          onClick={() => selected && save.mutate(selected)}
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
