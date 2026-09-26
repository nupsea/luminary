// What Luminary suggests installing on this computer, where a user will see it.
//
// Setup fetches only the embedder; everything else is the user's choice. Without
// this card the suggestions lived in Settings alone, where a new user never looks.

import { useState } from "react"
import { Sparkles } from "lucide-react"

import { InstallComponentButton } from "@/components/setup/InstallComponentButton"
import { useComponents } from "@/hooks/useSetup"

const DISMISSED_KEY = "luminary.modelSuggestions.dismissed"

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === "1"
  } catch {
    return false
  }
}

export function ModelSuggestions() {
  const { data: components } = useComponents()
  const [dismissed, setDismissed] = useState(readDismissed)

  const suggested = (components ?? []).filter((c) => c.recommended && c.offered && !c.installed)
  if (dismissed || suggested.length === 0) return null

  function dismiss() {
    setDismissed(true)
    try {
      localStorage.setItem(DISMISSED_KEY, "1")
    } catch {
      // Only this session remembers it; nothing is lost.
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card/60 p-4">
      <div className="flex items-start gap-2.5">
        <Sparkles size={15} className="mt-0.5 shrink-0 text-primary" />
        <div className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold text-foreground">Suggested for this computer</h2>
          <p className="max-w-2xl text-xs text-muted-foreground">
            Luminary works without these. Each is a one-time download that runs on this
            computer, and you can add or remove them any time in Settings.
          </p>
        </div>
      </div>

      <ul className="flex flex-col gap-3 pl-6">
        {suggested.map((c) => (
          <li key={c.id} className="flex flex-col gap-1">
            <span className="text-xs font-medium text-foreground">{c.label}</span>
            <span className="text-xs text-muted-foreground">{c.description}</span>
            <InstallComponentButton componentId={c.id} className="mt-1" />
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={dismiss}
        className="self-start pl-6 text-xs text-muted-foreground hover:text-foreground"
      >
        Not now
      </button>
    </section>
  )
}
