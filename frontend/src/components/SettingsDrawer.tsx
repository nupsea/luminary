import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Monitor, Moon, RefreshCw, Settings, Sun, X } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { type CloudProvider, hasKeyFor, saveBlocker } from "@/lib/cloudModels"
import { pendingRouting } from "@/lib/llmRouting"
import { providerSetup } from "@/lib/engineOffer"
import { ALWAYS_LOCAL, ENGINE_MODES, engineMode } from "@/lib/engineModes"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/store"

import { apiGet, apiPatch, apiPost } from "@/lib/apiClient"
import { RoutingTable } from "@/components/settings/RoutingTable"
import { CloudProviderSettings } from "@/components/settings/CloudProviderSettings"
import { invalidateKeyedQueries, saveProviderKey } from "@/lib/cloudKeys"
import { API_BASE } from "@/lib/config"
import { getTheme, setTheme, type Theme } from "@/lib/theme"
import { DevicesSettings } from "@/components/settings/DevicesSettings"
import { ModelsAndComponents } from "@/components/settings/ModelsAndComponents"
import { type ModelDrift } from "@/components/settings/ModelDriftNotice"
import { OreillySettings } from "@/components/settings/OreillySettings"
import { ReportIssue } from "@/components/settings/ReportIssue"
import type { components } from "@/types/api"
import { refreshModelState } from "@/lib/setupApi"

// Types

interface LLMSettings {
  // New DB-backed fields
  mode: "private" | "cloud" | "hybrid"
  provider: string
  model: string
  has_openai_key: boolean
  has_anthropic_key: boolean
  has_google_key: boolean
  // Backward-compat
  processing_mode: string
  active_model: string
  available_local_models: string[]
  // The on-device models actually routed to, resolved from the stored choice
  // or the configured default.
  local_chat_model: string
  vision_model: string
  ollama_reachable: boolean
  keyring_available: boolean
}

interface StorageInfo {
  data_dir: string
  raw_mb: number
  vectors_mb: number
  models_mb: number
}

// API functions

const fetchLLMSettings = (): Promise<LLMSettings> =>
  apiGet<LLMSettings>("/settings/llm")

type ModelResidencyResponse = components["schemas"]["ModelResidencyResponse"]

const fetchModelResidency = (): Promise<ModelResidencyResponse> =>
  apiGet<ModelResidencyResponse>("/settings/models")

const patchLLMSettings = (updates: {
  mode?: string
  provider?: string
  model?: string
  local_chat_model?: string
  vision_model?: string
  openai_api_key?: string | null
  anthropic_api_key?: string | null
  google_api_key?: string | null
}): Promise<void> => apiPatch("/settings/llm", updates)

const fetchStorage = (): Promise<StorageInfo> =>
  apiGet<StorageInfo>("/settings/storage")

interface RegenStatus {
  status: "idle" | "running" | "done" | "error"
  started_at: string | null
  finished_at: string | null
  concepts: number | null
  error: string | null
}

const fetchRegenStatus = (): Promise<RegenStatus> =>
  apiGet<RegenStatus>("/concepts/regenerate/status")

interface RetrievalSettings {
  rerank_enabled: boolean
}

const fetchRetrievalSettings = (): Promise<RetrievalSettings> =>
  apiGet<RetrievalSettings>("/settings/retrieval")

const patchRetrievalSettings = (updates: RetrievalSettings): Promise<RetrievalSettings> =>
  apiPatch("/settings/retrieval", updates)

function RetrievalControl() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ["retrieval-settings"],
    queryFn: fetchRetrievalSettings,
    staleTime: 60_000,
  })
  const mutation = useMutation({
    mutationFn: patchRetrievalSettings,
    onSuccess: (fresh) => queryClient.setQueryData(["retrieval-settings"], fresh),
    onError: () => toast.error("Could not update retrieval settings"),
  })
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold text-foreground">Retrieval</h3>
      <label className="flex cursor-pointer items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-foreground">Answer reranking</p>
          <p className="text-xs text-muted-foreground">
            Re-score search results with a local cross-encoder before answering. Better
            answers on paraphrased questions; adds a fraction of a second per question on CPU.
          </p>
        </div>
        <input
          type="checkbox"
          checked={data?.rerank_enabled ?? true}
          disabled={!data || mutation.isPending}
          onChange={(e) => mutation.mutate({ rerank_enabled: e.target.checked })}
          className="mt-0.5 h-4 w-4 flex-shrink-0 rounded border-border accent-primary"
        />
      </label>
    </section>
  )
}

interface BackgroundSettings {
  chapter_backfill: boolean
  quiet_background: boolean
}

const BACKGROUND_ROWS: { key: keyof BackgroundSettings; label: string; help: string }[] = [
  {
    key: "quiet_background",
    label: "Quiet background work",
    help:
      "Work nobody is waiting on (figures, summaries, chapter questions) rests between steps, " +
      "keeping the machine cooler and quieter. It finishes about twice as late.",
  },
  {
    key: "chapter_backfill",
    label: "Write chapter questions ahead",
    help:
      "Write questions for the chapters of books you are reading while the machine is free. " +
      "Off: only a new book's first chapters get questions.",
  },
]

function BackgroundControl() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ["background-settings"],
    queryFn: () => apiGet<BackgroundSettings>("/settings/background"),
    staleTime: 60_000,
  })
  const mutation = useMutation({
    mutationFn: (updates: Partial<BackgroundSettings>): Promise<BackgroundSettings> =>
      apiPatch("/settings/background", updates),
    onSuccess: (fresh) => queryClient.setQueryData(["background-settings"], fresh),
    onError: () => toast.error("Could not update background settings"),
  })
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-foreground">Background work</h3>
      {BACKGROUND_ROWS.map((row) => (
        <label key={row.key} className="flex cursor-pointer items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-foreground">{row.label}</p>
            <p className="text-xs text-muted-foreground">{row.help}</p>
          </div>
          <input
            type="checkbox"
            checked={data?.[row.key] ?? true}
            disabled={!data || mutation.isPending}
            onChange={(e) => mutation.mutate({ [row.key]: e.target.checked })}
            className="mt-0.5 h-4 w-4 flex-shrink-0 rounded border-border accent-primary"
          />
        </label>
      ))}
    </section>
  )
}

// Appearance: light / dark / follow-OS. Persists via lib/theme; the pre-paint
// script in index.html applies the choice before React mounts.
const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
]

function ThemeControl() {
  const [theme, setThemeState] = useState<Theme>(() => getTheme())
  return (
    <div className="grid grid-cols-3 gap-2">
      {THEME_OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = theme === value
        return (
          <button
            key={value}
            onClick={() => {
              setTheme(value)
              setThemeState(value)
            }}
            aria-pressed={active}
            className={cn(
              "flex flex-col items-center gap-1.5 rounded-lg border px-3 py-3 text-xs font-medium transition-colors",
              active
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Icon size={16} />
            {label}
          </button>
        )
      })}
    </div>
  )
}

// SettingsDrawer

interface SettingsDrawerProps {
  open: boolean
  onClose: () => void
}

function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const queryClient = useQueryClient()
  const reviewRemindersEnabled = useAppStore((s) => s.reviewRemindersEnabled)
  const setReviewRemindersEnabled = useAppStore((s) => s.setReviewRemindersEnabled)
  const { data: llm } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    staleTime: 30_000,
    refetchInterval: 30_000,
  })
  const { data: residency } = useQuery({
    queryKey: ["settings-models"],
    queryFn: fetchModelResidency,
    staleTime: 30_000,
    refetchInterval: 30_000,
  })
  const { data: storage, refetch: refetchStorage } = useQuery({
    queryKey: ["storage"],
    queryFn: fetchStorage,
    enabled: open,
  })

  // Manual concept-layer rebuild (the UI's "make concepts"): a background job we poll while it runs.
  const [confirmingRegen, setConfirmingRegen] = useState(false)
  const { data: regen } = useQuery({
    queryKey: ["concept-regen-status"],
    queryFn: fetchRegenStatus,
    enabled: open,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  })
  const startRegen = useMutation({
    mutationFn: () => apiPost("/concepts/regenerate"),
    onSuccess: () => {
      setConfirmingRegen(false)
      void queryClient.invalidateQueries({ queryKey: ["concept-regen-status"] })
    },
    onError: () => toast.error("Couldn't start the rebuild — is the backend running?"),
  })

  const [localMode, setLocalMode] = useState<"private" | "cloud" | "hybrid">("private")
  const [localProvider, setLocalProvider] = useState<CloudProvider>("openai")
  const [localModel, setLocalModel] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [isSaving, setIsSaving] = useState(false)

  const isCloudMode = localMode === "cloud" || localMode === "hybrid"

  const [pullModel, setPullModel] = useState("")
  const [pullLines, setPullLines] = useState<string[]>([])
  const [isPulling, setIsPulling] = useState(false)
  const pullScrollRef = useRef<HTMLDivElement>(null)

  // Reset from the saved choice only when it changes, not on every refetch:
  // saving a key refetches, and resetting then dropped a provider picked but not saved.
  const savedChoice = llm ? `${llm.mode}|${llm.provider}|${llm.model}` : null
  const [syncedChoice, setSyncedChoice] = useState<string | null>(null)
  if (llm && savedChoice !== syncedChoice) {
    setSyncedChoice(savedChoice)
    setLocalMode(llm.mode)
    setLocalProvider(llm.provider as CloudProvider)
    setLocalModel(llm.model)
  }

  const providerLabel = providerSetup(localProvider)?.label ?? localProvider
  const preview = pendingRouting(llm, { mode: localMode, provider: localProvider, model: localModel })
  const blocker = saveBlocker({
    mode: localMode,
    providerLabel,
    hasKey: hasKeyFor(localProvider, llm),
    pendingKey: apiKey.trim() !== "",
    model: localModel,
  })

  async function handleSave() {
    setIsSaving(true)
    try {
      // A key pasted but not checked yet goes through the same check as "Save key".
      if (isCloudMode && apiKey.trim()) {
        const check = await saveProviderKey(localProvider, apiKey.trim())
        if (!check.saved) {
          toast.error(check.message)
          return
        }
        setApiKey("")
      }
      await patchLLMSettings(
        isCloudMode
          ? { mode: localMode, provider: localProvider, model: localModel }
          : { mode: localMode },
      )
      toast.success("Settings saved")
      invalidateKeyedQueries(queryClient)
    } catch {
      toast.error("Failed to save settings")
    } finally {
      setIsSaving(false)
    }
  }

  async function handlePull() {
    const model = pullModel.trim()
    if (!model || isPulling) return
    setIsPulling(true)
    setPullLines([])

    try {
      // SSE stream: progress lines arrive via res.body.getReader();
      // apiClient's JSON path doesn't apply.
      // eslint-disable-next-line no-restricted-syntax
      const res = await fetch(`${API_BASE}/settings/ollama/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      })
      if (!res.ok || !res.body) throw new Error("Pull request failed")

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          const text = line.slice(6)
          if (text === "done") {
            toast.success(`Pulled ${model}`)
            void refreshModelState(queryClient)
          } else if (text) {
            setPullLines((prev) => [...prev, text])
            setTimeout(() => {
              pullScrollRef.current?.scrollTo({ top: pullScrollRef.current.scrollHeight })
            }, 0)
          }
        }
      }
    } catch {
      toast.error("Pull failed")
    } finally {
      setIsPulling(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Wider than the original 400px: the component catalogue carries a
          description, size, licence and an action per row, which wrapped to
          four lines each at the old width. */}
      <div className="relative z-10 flex h-full w-full max-w-[560px] flex-col border-l border-border bg-background shadow-xl sm:w-[92vw]">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-base font-semibold text-foreground">Settings</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-auto space-y-6 px-5 py-4">
          {/* Section 0: Appearance */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-foreground">Appearance</h3>
            <ThemeControl />
          </section>

          {/* Section 1: LLM Mode */}
          <section>
            <h3 className="mb-1 text-sm font-semibold text-foreground">Where models run</h3>
            <p className="mb-3 text-xs text-muted-foreground">{ALWAYS_LOCAL}</p>

            <div className="mb-4 grid grid-cols-3 gap-2">
              {ENGINE_MODES.map((mode) => (
                <label
                  key={mode.id}
                  className={cn(
                    "flex cursor-pointer flex-col gap-2 rounded-lg border p-3 transition-colors",
                    localMode === mode.id
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-muted-foreground",
                  )}
                >
                  <input
                    type="radio"
                    name="llmMode"
                    value={mode.id}
                    checked={localMode === mode.id}
                    onChange={() => setLocalMode(mode.id)}
                    className="sr-only"
                  />
                  <span className="text-sm font-semibold text-foreground">{mode.label}</span>
                  {mode.recommendation && (
                    <p className="text-[11px] font-medium text-primary">{mode.recommendation}</p>
                  )}
                  <p className="text-xs text-muted-foreground">{mode.summary}</p>
                </label>
              ))}
            </div>

            <p className="mb-3 text-xs text-muted-foreground">
              Sends: {engineMode(localMode).sends}
              {localMode !== "private" && " Uses your provider's quota and is billed by them."}
            </p>

            {isCloudMode && (
              <CloudProviderSettings
                llm={llm}
                provider={localProvider}
                onProviderChange={setLocalProvider}
                model={localModel}
                onModelChange={setLocalModel}
                apiKey={apiKey}
                onApiKeyChange={setApiKey}
                enabled={open}
              />
            )}

            <button
              onClick={() => void handleSave()}
              disabled={isSaving || blocker !== null}
              className="mt-4 w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {isSaving ? "Saving..." : `Save ${engineMode(localMode).label}${isCloudMode ? ` with ${providerLabel}` : ""}`}
            </button>
            {blocker && <p className="mt-1.5 text-center text-xs text-muted-foreground">{blocker}</p>}

            {(localMode === "private" || localMode === "hybrid") && (
              <div className="mt-5 space-y-2 border-t border-border pt-4">
                <p className="text-xs font-medium text-foreground">Download a local model</p>
                <p className="text-[11px] text-muted-foreground">
                  {localMode === "hybrid"
                    ? "Summaries, tags and titles run on this machine in Hybrid. "
                    : ""}
                  Pull any model from the Ollama library by name.
                </p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={pullModel}
                    onChange={(e) => setPullModel(e.target.value)}
                    placeholder="e.g. mistral"
                    className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  <button
                    onClick={() => void handlePull()}
                    disabled={!pullModel.trim() || isPulling}
                    className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-50"
                  >
                    {isPulling ? "Pulling..." : "Pull"}
                  </button>
                </div>
                {pullLines.length > 0 && (
                  <div
                    ref={pullScrollRef}
                    className="h-24 overflow-auto rounded-md bg-muted p-2 font-mono text-xs text-muted-foreground"
                  >
                    {pullLines.map((l, i) => (
                      <div key={i}>{l}</div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          <div className="border-t border-border" />

          {/* Read from the router, never written here: prose about routing drifts
              from routing. An unsaved choice is resolved by the same router. */}
          <section>
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-foreground">Which model does what</h3>
              {preview && (
                <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-400">
                  Not saved
                </span>
              )}
            </div>
            <p className="mb-3 text-xs text-muted-foreground">
              {preview
                ? `What ${engineMode(localMode).label}${isCloudMode ? ` with ${providerLabel}` : ""} will do once saved. Until then your saved ${engineMode(llm?.mode).label} settings keep running.`
                : "Your saved settings, job by job."}
            </p>
            <RoutingTable preview={preview} />
          </section>

          <div className="border-t border-border" />

          {/* Section 1.5: Models and optional components */}
          <section>
            <h3 className="mb-1 text-sm font-semibold text-foreground">Local models & components</h3>
            <p className="mb-3 text-xs text-muted-foreground">
              The models that run on this machine, and what to install. Downloads run in the
              background and can be removed again here.
            </p>
            <ModelsAndComponents
              llm={llm}
              narrowedDefaults={
                residency?.narrowed_defaults as
                  | Partial<Record<"chat" | "vision", ModelDrift>>
                  | undefined
              }
              onSave={async (updates) => {
                await patchLLMSettings(updates)
                await refreshModelState(queryClient)
              }}
            />
          </section>

          <div className="border-t border-border" />

          {/* Section 1.6: Reporting */}
          <section>
            <h3 className="mb-1 text-sm font-semibold text-foreground">Report an issue</h3>
            <p className="mb-3 text-xs text-muted-foreground">
              These are the details a maintainer needs to reproduce a problem.
            </p>
            <ReportIssue />
          </section>

          <div className="border-t border-border" />

          {/* Section 2: Storage */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground">Storage</h3>
              <button
                onClick={() => void refetchStorage()}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Refresh
              </button>
            </div>

            {storage ? (
              <div className="space-y-2">
                <p className="break-all font-mono text-xs text-muted-foreground">
                  {storage.data_dir}
                </p>
                <div className="grid grid-cols-3 gap-2">
                  {(
                    [
                      ["raw", storage.raw_mb],
                      ["vectors", storage.vectors_mb],
                      ["models", storage.models_mb],
                    ] as [string, number][]
                  ).map(([label, mb]) => (
                    <div key={label} className="rounded-md border border-border p-2 text-center">
                      <p className="text-lg font-semibold text-foreground">{mb}</p>
                      <p className="text-xs text-muted-foreground">{label} MB</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-16 animate-pulse rounded-md bg-muted" />
            )}
          </section>

          <div className="border-t border-border" />

          {/* Section 2.5: Knowledge concepts — manual rebuild (the UI's "make concepts") */}
          <section>
            <h3 className="mb-1 text-sm font-semibold text-foreground">Knowledge concepts</h3>
            <p className="mb-3 text-xs text-muted-foreground">
              Re-analyze your whole library to refresh the concept layer behind grounded answers
              and mastery. Takes a few minutes and needs Ollama running. Concept-level progress is
              recomputed — your flashcard review schedule is unaffected.
            </p>

            {regen?.status === "running" ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={15} className="animate-spin" />
                Rebuilding concepts… this can take a few minutes.
              </div>
            ) : confirmingRegen ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => startRegen.mutate()}
                  disabled={startRegen.isPending}
                  className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  Confirm rebuild
                </button>
                <button
                  onClick={() => setConfirmingRegen(false)}
                  className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground hover:bg-accent"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmingRegen(true)}
                className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-accent"
              >
                <RefreshCw size={14} /> Rebuild concepts
              </button>
            )}

            {regen?.status === "done" && !confirmingRegen && (
              <p className="mt-2 text-xs text-green-600">
                Done — rebuilt {regen.concepts ?? 0} concepts.
              </p>
            )}
            {regen?.status === "error" && !confirmingRegen && (
              <p className="mt-2 text-xs text-red-600">Rebuild failed: {regen.error}</p>
            )}
          </section>

          <div className="border-t border-border" />

          {/* Section 2.7: Retrieval — L3 reranker toggle */}
          <RetrievalControl />

          <div className="border-t border-border" />

          <BackgroundControl />

          <div className="border-t border-border" />

          <section>
            <h3 className="mb-1 text-sm font-semibold text-foreground">Devices</h3>
            <DevicesSettings />
          </section>

          <div className="border-t border-border" />

          {/* Section 2.8: Subscriptions & Integrations */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-foreground">Subscriptions & Integrations</h3>
            <OreillySettings />
          </section>

          <div className="border-t border-border" />

          {/* Section 3: Notifications */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-foreground">Notifications</h3>
            <label className="flex cursor-pointer items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-foreground">Review reminders</p>
                <p className="text-xs text-muted-foreground">
                  Show a desktop notification when cards are due (at most once every 4 hours).
                </p>
              </div>
              <input
                type="checkbox"
                checked={reviewRemindersEnabled}
                onChange={(e) => setReviewRemindersEnabled(e.target.checked)}
                className="mt-0.5 h-4 w-4 flex-shrink-0 rounded border-border accent-primary"
              />
            </label>
            {typeof Notification !== "undefined" && Notification.permission === "denied" && (
              <p className="mt-2 text-xs text-amber-600">
                Notifications are blocked by your browser. Enable them in browser settings to receive reminders.
              </p>
            )}
          </section>

        </div>
      </div>
    </div>
  )
}

// LLMModeBadge — shown in sidebar footer. Reads the saved setting like every
// other view; nothing copies the mode into client state.

interface LLMModeBadgeProps {
  onClick: () => void
}

export function LLMModeBadge({ onClick }: LLMModeBadgeProps) {
  const { data } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  const mode = data?.mode ?? "private"
  const modeLabel = engineMode(mode).label
  const ollamaDown = mode === "private" && data?.processing_mode === "unavailable"
  const dotColor =
    ollamaDown ? "bg-red-500" : mode === "cloud" ? "bg-blue-500" : mode === "hybrid" ? "bg-purple-500" : "bg-green-500"
  const label = ollamaDown
    ? `${modeLabel} (local model unavailable)`
    : mode === "private"
      ? modeLabel
      : `${modeLabel}: ${data?.model ?? ""}`

  return (
    <button
      onClick={onClick}
      title={label}
      className="relative flex h-10 w-10 items-center justify-center rounded-md text-sidebar-foreground transition-colors hover:bg-accent"
    >
      <Settings size={20} />
      <span
        className={cn(
          "absolute right-1.5 top-1.5 h-2 w-2 rounded-full border border-background",
          dotColor,
        )}
      />
    </button>
  )
}

export { SettingsDrawer }
