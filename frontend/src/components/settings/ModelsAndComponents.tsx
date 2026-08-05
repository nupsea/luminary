// Install the optional pieces, and choose which model actually gets used.
//
// Both halves were unreachable after first run: the catalogue was only ever
// rendered by the setup screen, and the local chat and vision models came from
// config with no way to change them. Installing a model you then could not
// select is not a setting.

import { useEffect, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { InstallComponentButton } from "@/components/setup/InstallComponentButton"
import { useComponents } from "@/hooks/useSetup"
import { formatBytes, uninstallComponent, type Component } from "@/lib/setupApi"
import { cn } from "@/lib/utils"

interface ModelChoice {
  local_chat_model: string
  vision_model: string
  available_local_models: string[]
  ollama_reachable: boolean
}

interface Props {
  llm: ModelChoice | undefined
  onSave: (updates: { local_chat_model?: string; vision_model?: string }) => Promise<void>
}

function ComponentRow({ component }: { component: Component }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const remove = useMutation({
    mutationFn: () => uninstallComponent(component.id),
    onSuccess: async () => {
      setConfirming(false)
      toast.success(`Removed ${component.label.toLowerCase()}`)
      await queryClient.invalidateQueries({ queryKey: ["setup"] })
      await queryClient.invalidateQueries({ queryKey: ["llm-settings"] })
    },
    onError: () => toast.error(`Couldn't remove ${component.label.toLowerCase()}`),
  })

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">{component.label}</span>
            {component.installed && (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-500">
                <Check size={12} /> Installed
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{component.description}</p>
        </div>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {formatBytes(component.size_bytes)}
        </span>
      </div>

      {component.enables.length > 0 && (
        <p className="text-xs text-muted-foreground">Enables: {component.enables.join(", ")}</p>
      )}
      <p className="text-xs text-muted-foreground/70">{component.licence}</p>

      {component.installed ? (
        confirming ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              className="inline-flex items-center gap-1.5 rounded-md border border-red-300 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950/30"
            >
              {remove.isPending && <Loader2 size={12} className="animate-spin" />}
              Remove {component.ref}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="inline-flex items-center gap-1.5 self-start text-xs text-muted-foreground hover:text-foreground"
          >
            <Trash2 size={12} /> Remove
          </button>
        )
      ) : (
        <InstallComponentButton componentId={component.id} />
      )}
    </div>
  )
}

function ModelPicker({
  label,
  hint,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string
  hint: string
  value: string
  options: string[]
  onChange: (value: string) => void
  disabled: boolean
}) {
  // A model set in config but not pulled would otherwise vanish from the list
  // and silently reset the selection to something else.
  const choices = value && !options.includes(value) ? [value, ...options] : options

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-foreground">{label}</label>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground disabled:opacity-60"
      >
        {choices.length === 0 && <option value="">No models installed</option>}
        {choices.map((m) => (
          <option key={m} value={m}>
            {m.replace(/^ollama\//, "")}
          </option>
        ))}
      </select>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

export function ModelsAndComponents({ llm, onSave }: Props) {
  const { data: components = [], isLoading } = useComponents()
  const [chat, setChat] = useState("")
  const [vision, setVision] = useState("")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!llm) return
    setChat(llm.local_chat_model)
    setVision(llm.vision_model)
  }, [llm])

  const options = llm?.available_local_models ?? []
  const dirty = !!llm && (chat !== llm.local_chat_model || vision !== llm.vision_model)

  async function save() {
    setSaving(true)
    try {
      await onSave({ local_chat_model: chat, vision_model: vision })
      toast.success("Models updated")
    } catch {
      toast.error("Couldn't save the model choice")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-3">
        <ModelPicker
          label="Chat model"
          hint="Answers questions and generates flashcards on this machine."
          value={chat}
          options={options}
          onChange={setChat}
          disabled={!llm?.ollama_reachable}
        />
        <ModelPicker
          label="Vision model"
          hint="Reads figures and diagrams during ingestion. Install one below to enable it."
          value={vision}
          options={options}
          onChange={setVision}
          disabled={!llm?.ollama_reachable}
        />
        {!llm?.ollama_reachable && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            The local model server isn't responding, so the installed models can't be listed.
          </p>
        )}
        <button
          onClick={() => void save()}
          disabled={!dirty || saving}
          className={cn(
            "rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground",
            "hover:bg-primary/90 disabled:opacity-50",
          )}
        >
          {saving ? "Saving…" : "Save model choice"}
        </button>
      </div>

      <div className="space-y-2">
        <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Downloadable components
        </h4>
        {isLoading ? (
          <div className="h-24 animate-pulse rounded-md bg-muted" />
        ) : components.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nothing optional to install.</p>
        ) : (
          components.map((c) => <ComponentRow key={c.id} component={c} />)
        )}
      </div>
    </div>
  )
}
