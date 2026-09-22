// Local, Hybrid and Cloud: what each mode is, defined once for every surface, so
// first run and Settings cannot describe one stored value in two wordings. Pure and
// in lib/ so the wording rules are unit-tested.

import { joinLabels, type RoutingResponse } from "@/lib/llmRouting"

export type EngineMode = "private" | "hybrid" | "cloud"

export interface EngineModeDef {
  id: EngineMode
  label: string
  /** What runs where, in one sentence. */
  summary: string
  /** What reaches the provider, stated as data rather than reassurance. */
  sends: string
  /** What this mode means on a host that cannot run a local model. */
  onUnsupportedHost: string
  needsKey: boolean
}

export const ALWAYS_LOCAL =
  "Indexing, search, transcription and your learner record stay on this machine in every mode."

export const ENGINE_MODES: readonly EngineModeDef[] = [
  {
    id: "private",
    label: "Local",
    summary: "Everything runs on this machine. No account, no key.",
    sends: "Nothing leaves this machine.",
    onUnsupportedHost:
      "This machine can't run a local model, so only reading, search, notes and review work.",
    needsKey: false,
  },
  {
    id: "hybrid",
    label: "Hybrid",
    summary:
      "Answers and cards use your API key. Summaries, tags and titles are made on this machine.",
    sends: "Your question and the passages retrieved for it.",
    onUnsupportedHost:
      "Answers and cards work. Summaries, tags and titles are not made, because this machine can't run a local model.",
    needsKey: true,
  },
  {
    id: "cloud",
    label: "Cloud",
    summary: "Answers, cards, summaries, tags and titles all use your API key.",
    sends:
      "Your question with the passages retrieved for it, and sections of your documents for summaries, tags and titles.",
    onUnsupportedHost: "Everything works with your key except describing figures.",
    needsKey: true,
  },
] as const

export function engineMode(id: string | undefined): EngineModeDef {
  return ENGINE_MODES.find((m) => m.id === id) ?? ENGINE_MODES[0]
}

/**
 * The text shown when a model call fails: the server's message, which names the
 * actual situation, never a client-side guess from the mode.
 */
export function modelUnavailableMessage(serverMessage?: string | null): string {
  const text = serverMessage?.trim()
  return text ? text : "The model could not be reached. Check where answers come from in Settings."
}

export interface HostVerdict {
  supported: boolean
  host: string
  message: string | null
}

/**
 * The banner line for a host that cannot run a local model, or null. Built from
 * the routing report's refused rows, not the mode.
 */
export function hostNotice(
  host: HostVerdict | undefined,
  routing: RoutingResponse | undefined,
): string | null {
  if (!host || host.supported) return null
  if (!routing) return host.message
  const notRun = routing.work.filter((w) => w.refused_reason)
  if (notRun.length === 0) return null
  const mode = engineMode(routing.mode)
  const labels = joinLabels(notRun.map((w) => w.label.toLowerCase()))
  const next =
    mode.id === "private"
      ? " Hybrid or Cloud mode runs answers and cards with your API key; change it in Settings."
      : mode.id === "hybrid"
        ? " Cloud mode makes summaries, tags and titles with your API key and sends sections of your documents to your provider; change it in Settings."
        : ""
  return `This machine can't run a local model at a usable speed (${host.host}). In ${mode.label} mode, not run: ${labels}.${next}`
}
