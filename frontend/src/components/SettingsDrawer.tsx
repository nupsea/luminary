import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Cloud, Settings, Shield, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/store"

const API_BASE = "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LLMSettings {
  // New DB-backed fields
  mode: "private" | "cloud"
  provider: string
  model: string
  has_openai_key: boolean
  has_anthropic_key: boolean
  has_google_key: boolean
  // Backward-compat
  processing_mode: string
  active_model: string
  available_local_models: string[]
}

interface StorageInfo {
  data_dir: string
  raw_mb: number
  vectors_mb: number
  models_mb: number
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

async function fetchLLMSettings(): Promise<LLMSettings> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) throw new Error("Failed to fetch LLM settings")
  return res.json() as Promise<LLMSettings>
}

async function patchLLMSettings(updates: {
  mode?: string
  provider?: string
  model?: string
  openai_api_key?: string | null
  anthropic_api_key?: string | null
  google_api_key?: string | null
}): Promise<void> {
  const res = await fetch(`${API_BASE}/settings/llm`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error("Failed to save settings")
}

async function fetchStorage(): Promise<StorageInfo> {
  const res = await fetch(`${API_BASE}/settings/storage`)
  if (!res.ok) throw new Error("Failed to fetch storage info")
  return res.json() as Promise<StorageInfo>
}

// ---------------------------------------------------------------------------
// SettingsDrawer
// ---------------------------------------------------------------------------

interface SettingsDrawerProps {
  open: boolean
  onClose: () => void
}

function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const queryClient = useQueryClient()
  const { data: llm } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    refetchInterval: 30_000,
  })
  const { data: storage, refetch: refetchStorage } = useQuery({
    queryKey: ["storage"],
    queryFn: fetchStorage,
    enabled: open,
  })

  const [localMode, setLocalMode] = useState<"private" | "cloud">("private")
  const [localProvider, setLocalProvider] = useState("openai")
  const [localModel, setLocalModel] = useState("gpt-4o-mini")
  const [apiKey, setApiKey] = useState("")
  const [isSaving, setIsSaving] = useState(false)

  const [pullModel, setPullModel] = useState("")
  const [pullLines, setPullLines] = useState<string[]>([])
  const [isPulling, setIsPulling] = useState(false)
  const pullScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (llm) {
      setLocalMode(llm.mode)
      setLocalProvider(llm.provider)
      setLocalModel(llm.model)
    }
  }, [llm])

  async function handleSave() {
    setIsSaving(true)
    try {
      const updates: {
        mode?: string
        provider?: string
        model?: string
        openai_api_key?: string | null
        anthropic_api_key?: string | null
        google_api_key?: string | null
      } = {
        mode: localMode,
        provider: localProvider,
        model: localModel,
      }
      if (apiKey.trim()) {
        if (localProvider === "openai") updates.openai_api_key = apiKey.trim()
        else if (localProvider === "anthropic") updates.anthropic_api_key = apiKey.trim()
        else updates.google_api_key = apiKey.trim()
      }
      await patchLLMSettings(updates)
      setApiKey("")
      toast.success("Settings saved")
      void queryClient.invalidateQueries({ queryKey: ["llm-settings"] })
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
            void queryClient.invalidateQueries({ queryKey: ["llm-settings"] })
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

  const hasKeyForProvider =
    localProvider === "openai"
      ? llm?.has_openai_key
      : localProvider === "anthropic"
        ? llm?.has_anthropic_key
        : llm?.has_google_key

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      <div className="relative z-10 flex h-full w-[400px] flex-col border-l border-border bg-background shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-base font-semibold text-foreground">Settings</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-auto space-y-6 px-5 py-4">
          {/* Section 1: LLM Mode */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-foreground">LLM Mode</h3>

            <div className="mb-4 grid grid-cols-2 gap-3">
              <label
                className={cn(
                  "flex cursor-pointer flex-col gap-2 rounded-lg border p-3 transition-colors",
                  localMode === "private"
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground",
                )}
              >
                <input
                  type="radio"
                  name="llmMode"
                  value="private"
                  checked={localMode === "private"}
                  onChange={() => setLocalMode("private")}
                  className="sr-only"
                />
                <div className="flex items-center gap-2">
                  <Shield size={16} className="text-green-600" />
                  <span className="text-sm font-semibold text-foreground">Private</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Your data never leaves your device. Uses local Ollama.
                </p>
              </label>

              <label
                className={cn(
                  "flex cursor-pointer flex-col gap-2 rounded-lg border p-3 transition-colors",
                  localMode === "cloud"
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground",
                )}
              >
                <input
                  type="radio"
                  name="llmMode"
                  value="cloud"
                  checked={localMode === "cloud"}
                  onChange={() => setLocalMode("cloud")}
                  className="sr-only"
                />
                <div className="flex items-center gap-2">
                  <Cloud size={16} className="text-blue-500" />
                  <span className="text-sm font-semibold text-foreground">Cloud</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Faster responses using OpenAI, Anthropic, or Google.
                </p>
              </label>
            </div>

            {localMode === "cloud" && (
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    Provider
                  </label>
                  <select
                    value={localProvider}
                    onChange={(e) => setLocalProvider(e.target.value)}
                    className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="gemini">Google Gemini</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    Model
                  </label>
                  <input
                    type="text"
                    value={localModel}
                    onChange={(e) => setLocalModel(e.target.value)}
                    placeholder="gpt-4o-mini"
                    className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>

                <div>
                  <label className="mb-1 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                    API Key
                    {hasKeyForProvider ? (
                      <span className="text-green-600">Key configured</span>
                    ) : (
                      <span className="text-amber-600">Key not set</span>
                    )}
                  </label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={hasKeyForProvider ? "Enter to replace" : "Paste API key"}
                    className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
            )}

            {localMode === "private" && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Pull a model</p>
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
                    className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
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

            <button
              onClick={() => void handleSave()}
              disabled={isSaving}
              className="mt-4 w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {isSaving ? "Saving..." : "Save"}
            </button>
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

          {/* Section 3: Privacy notice */}
          <section>
            <p className="text-xs text-muted-foreground">
              {localMode === "private"
                ? "No content leaves your machine. All processing happens on-device using Ollama and local embedding models."
                : "API calls are sent to the configured cloud provider. Your documents are included in requests."}
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// LLMModeBadge — shown in sidebar footer, populates Zustand store
// ---------------------------------------------------------------------------

interface LLMModeBadgeProps {
  onClick: () => void
}

export function LLMModeBadge({ onClick }: LLMModeBadgeProps) {
  const { data } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    refetchInterval: 30_000,
  })
  const setLlmMode = useAppStore((s) => s.setLlmMode)

  useEffect(() => {
    if (data) {
      setLlmMode(data.mode, data.provider)
    }
  }, [data, setLlmMode])

  const mode = data?.mode ?? "private"
  const dotColor = mode === "cloud" ? "bg-blue-500" : "bg-green-500"
  const label = mode === "cloud" ? `Cloud: ${data?.model ?? ""}` : "Private"

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
