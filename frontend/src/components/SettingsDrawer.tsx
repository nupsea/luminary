import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Settings, X } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

const API_BASE = "http://localhost:8000"

type ProcessingMode = "local" | "cloud" | "unavailable"

interface CloudProvider {
  name: string
  available: boolean
}

interface LLMSettings {
  processing_mode: ProcessingMode
  active_model: string
  available_local_models: string[]
  cloud_providers: CloudProvider[]
}

interface StorageInfo {
  data_dir: string
  raw_mb: number
  vectors_mb: number
  models_mb: number
}

type CloudTab = "openai" | "anthropic" | "google"

async function fetchLLMSettings(): Promise<LLMSettings> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) throw new Error("Failed to fetch LLM settings")
  return res.json() as Promise<LLMSettings>
}

async function fetchStorage(): Promise<StorageInfo> {
  const res = await fetch(`${API_BASE}/settings/storage`)
  if (!res.ok) throw new Error("Failed to fetch storage info")
  return res.json() as Promise<StorageInfo>
}

async function patchSettings(updates: Record<string, string>): Promise<void> {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error("Failed to save settings")
}

const CLOUD_KEY_MAP: Record<CloudTab, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  google: "GOOGLE_API_KEY",
}

const DOT_COLOR: Record<ProcessingMode, string> = {
  local: "bg-green-500",
  cloud: "bg-blue-500",
  unavailable: "bg-red-500",
}

function modeLabel(settings: LLMSettings | undefined): string {
  if (!settings) return "..."
  if (settings.processing_mode === "local") return `local: ${settings.active_model}`
  if (settings.processing_mode === "cloud") return `cloud: ${settings.active_model}`
  return "unavailable"
}

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

  const [subMode, setSubMode] = useState<"local" | "cloud">("local")
  const [cloudTab, setCloudTab] = useState<CloudTab>("openai")
  const [apiKeys, setApiKeys] = useState<Record<CloudTab, string>>({
    openai: "",
    anthropic: "",
    google: "",
  })
  const [pullModel, setPullModel] = useState("")
  const [pullLines, setPullLines] = useState<string[]>([])
  const [isPulling, setIsPulling] = useState(false)
  const pullScrollRef = useRef<HTMLDivElement>(null)

  async function handleSaveKey(tab: CloudTab) {
    const key = apiKeys[tab].trim()
    if (!key) return
    try {
      await patchSettings({ [CLOUD_KEY_MAP[tab]]: key })
      toast.success("API key saved")
      void queryClient.invalidateQueries({ queryKey: ["llm-settings"] })
    } catch {
      toast.error("Failed to save API key")
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

  const mode = llm?.processing_mode ?? "unavailable"

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Drawer panel */}
      <div className="relative z-10 flex h-full w-[400px] flex-col border-l border-border bg-background shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-base font-semibold text-foreground">Settings</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-6">
          {/* Section 1: LLM Mode */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-foreground">LLM Mode</h3>

            {/* Current mode indicator */}
            <div className="mb-3 flex items-center gap-2">
              <span className={cn("h-2.5 w-2.5 rounded-full", DOT_COLOR[mode])} />
              <span className="text-sm text-muted-foreground">{modeLabel(llm)}</span>
            </div>

            {/* Local / Cloud radio */}
            <div className="mb-4 flex gap-4">
              {(["local", "cloud"] as const).map((m) => (
                <label key={m} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="subMode"
                    value={m}
                    checked={subMode === m}
                    onChange={() => setSubMode(m)}
                    className="accent-primary"
                  />
                  <span className="text-sm capitalize text-foreground">{m}</span>
                </label>
              ))}
            </div>

            {subMode === "local" ? (
              <div className="space-y-4">
                {/* Available models */}
                {llm && llm.available_local_models.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground">Available models</p>
                    {llm.available_local_models.map((m) => (
                      <label key={m} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          name="localModel"
                          value={m}
                          defaultChecked={m === llm.active_model}
                          className="accent-primary"
                        />
                        <span className="text-sm text-foreground font-mono">{m}</span>
                      </label>
                    ))}
                  </div>
                )}

                {/* Pull model */}
                <div>
                  <p className="mb-2 text-xs font-medium text-muted-foreground">Pull a model</p>
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
                      className="mt-2 h-24 overflow-auto rounded-md bg-muted p-2 font-mono text-xs text-muted-foreground"
                    >
                      {pullLines.map((l, i) => (
                        <div key={i}>{l}</div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {/* Cloud provider tabs */}
                <div className="flex gap-1 rounded-md bg-muted p-1">
                  {(["openai", "anthropic", "google"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setCloudTab(t)}
                      className={cn(
                        "flex-1 rounded py-1.5 text-xs font-medium capitalize transition-colors",
                        cloudTab === t
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {t}
                    </button>
                  ))}
                </div>

                <div className="flex gap-2">
                  <input
                    type="password"
                    value={apiKeys[cloudTab]}
                    onChange={(e) =>
                      setApiKeys((prev) => ({ ...prev, [cloudTab]: e.target.value }))
                    }
                    placeholder={`${CLOUD_KEY_MAP[cloudTab]}`}
                    className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  <button
                    onClick={() => void handleSaveKey(cloudTab)}
                    disabled={!apiKeys[cloudTab].trim()}
                    className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                  >
                    Save
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* Divider */}
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

          {/* Divider */}
          <div className="border-t border-border" />

          {/* Section 3: Privacy notice */}
          <section>
            <p className="text-xs text-muted-foreground">
              In local mode, no content leaves your machine. All processing happens on-device using
              Ollama and local embedding models.
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}

interface LLMModeBadgeProps {
  onClick: () => void
}

export function LLMModeBadge({ onClick }: LLMModeBadgeProps) {
  const { data } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: fetchLLMSettings,
    refetchInterval: 30_000,
  })

  const mode: ProcessingMode = data?.processing_mode ?? "unavailable"
  const label = modeLabel(data)

  return (
    <button
      onClick={onClick}
      title={label}
      className="flex h-10 w-10 items-center justify-center rounded-md text-sidebar-foreground transition-colors hover:bg-accent relative"
    >
      <Settings size={20} />
      <span
        className={cn(
          "absolute right-1.5 top-1.5 h-2 w-2 rounded-full border border-background",
          DOT_COLOR[mode],
        )}
      />
    </button>
  )
}

export { SettingsDrawer }
