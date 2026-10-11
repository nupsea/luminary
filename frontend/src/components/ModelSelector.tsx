// ModelSelector -- shows the model a surface is using and overrides it per request.
//
// Shared by Ask, Study, Practice and the blog dialog: a wrong answer and a wrong
// card prompt the same question ("which model wrote this?"). "Auto" follows
// Settings; a concrete id overrides only this surface, and the info panel says so.

import { Cpu, Info } from "lucide-react"
import { useState } from "react"

import { shortModelLabel } from "@/lib/chatSettingsUtils"
import { modelScopeCopy, type ModelSurface } from "@/lib/modelScope"
import { cn } from "@/lib/utils"

interface ModelSelectorProps {
  value: string // per-request override; "" = Auto, the Settings route
  onChange: (model: string) => void
  localModels: string[]
  cloudModels: string[]
  effectiveDefault: string
  surface: ModelSurface
}

export function ModelSelector({
  value,
  onChange,
  localModels,
  cloudModels,
  effectiveDefault,
  surface,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false)
  const copy = modelScopeCopy(surface, value, effectiveDefault)
  const pinned = value !== ""

  return (
    <div className="relative flex items-center gap-1">
      <label
        className={cn(
          "flex items-center gap-1.5 rounded-md border bg-background px-2.5 py-1.5 text-xs text-foreground transition-colors hover:bg-accent",
          pinned ? "border-amber-400 dark:border-amber-700" : "border-border",
        )}
        title={copy.status}
      >
        <Cpu size={13} className="shrink-0 text-muted-foreground" />
        <span className="text-muted-foreground">{pinned ? "Pinned:" : "Model:"}</span>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Model for this surface"
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
      </label>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="What this model choice affects"
        className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <Info size={13} />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="What this model choice affects"
          className="absolute right-0 top-full z-30 mt-1 w-72 space-y-2 rounded-lg border border-border bg-popover p-3 text-xs text-popover-foreground shadow-lg"
        >
          <p className="font-medium">{copy.status}</p>
          <div>
            <p className="text-muted-foreground">Changes</p>
            <p>{copy.affects}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Does not change</p>
            <p>{copy.leaves}</p>
          </div>
          {pinned && (
            <button
              type="button"
              onClick={() => {
                onChange("")
                setOpen(false)
              }}
              className="text-primary hover:underline"
            >
              Use Auto
            </button>
          )}
        </div>
      )}
    </div>
  )
}
