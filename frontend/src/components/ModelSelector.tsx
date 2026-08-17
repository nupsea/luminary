// ModelSelector -- shows the model a surface is using and overrides it per request.
//
// Shared by Ask and Study rather than copied: a card that comes back wrong and a
// chat answer that comes back wrong prompt the same question ("which model wrote
// this?"), and one of the two surfaces could not answer it at all until now.
// "Auto" follows Settings; a concrete id overrides only the requests this surface
// sends.

import { Cpu } from "lucide-react"
import { shortModelLabel } from "@/lib/chatSettingsUtils"

interface ModelSelectorProps {
  value: string // per-request override; "" = use the app default
  onChange: (model: string) => void
  localModels: string[]
  cloudModels: string[]
  effectiveDefault: string
  title?: string
}

export function ModelSelector({
  value,
  onChange,
  localModels,
  cloudModels,
  effectiveDefault,
  title,
}: ModelSelectorProps) {
  const current = value ? shortModelLabel(value) : shortModelLabel(effectiveDefault)
  return (
    <label
      className="flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-foreground hover:bg-accent transition-colors"
      title={
        title ??
        "Model used here. 'Auto' follows your Settings; pick another to override just this surface."
      }
    >
      <Cpu size={13} className="shrink-0 text-muted-foreground" />
      <span className="text-muted-foreground">Model:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[160px] cursor-pointer truncate bg-transparent font-medium text-foreground focus:outline-none"
      >
        <option value="">Auto · {shortModelLabel(effectiveDefault)}</option>
        {localModels.length > 0 && (
          <optgroup label="Local (Ollama)">
            {localModels.map((m) => (
              <option key={m} value={m}>
                {shortModelLabel(m)}
              </option>
            ))}
          </optgroup>
        )}
        {cloudModels.length > 0 && (
          <optgroup label="Cloud">
            {cloudModels.map((m) => (
              <option key={m} value={m}>
                {shortModelLabel(m)}
              </option>
            ))}
          </optgroup>
        )}
      </select>
      {value && <span className="sr-only">{current}</span>}
    </label>
  )
}
