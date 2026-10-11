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
  /** Why this mode is the one to pick for a given use, or absent. Never preselects it (I-16). */
  recommendation?: string
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
    // The writer model, not the prompt, is the remaining lever on card quality (#230).
    recommendation:
      "Recommended for Ask and Practice: a cloud model writes better answers and practice cards than the small local model.",
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

/** Shown only when a failed model call carried no message of its own. */
export const LOCAL_MODEL_DOWN =
  "The local model is not answering. Quit Luminary and reopen it, then try again."

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
  measured?: boolean
  /** Share of the model's bytes on the graphics card; below 1 the rest runs on the processor. */
  gpu_share?: number | null
  /** A chat-model load is under way whose measurement can still turn the verdict. */
  settling?: boolean
  /** The model server keeps old prompts in memory without a bound (I-64). */
  prompt_cache_unbounded?: boolean
  /** How the local Ollama was started, which decides its fix. */
  ollama_launch?: "macos_app" | "launchd" | "systemd" | "windows" | "terminal" | null
  /** The launchd label or systemd unit that restarts it. */
  ollama_service?: string | null
}

const MAC_FORGETS = " macOS forgets this setting when the Mac restarts; this notice returns if it does."

// `launchctl setenv` reaches only what launchd starts; a terminal's `ollama serve`
// reads its shell, a systemd server its unit (I-64).
function promptCacheFix(host: HostVerdict): string {
  const unit = host.ollama_service
  switch (host.ollama_launch) {
    case "macos_app":
      return (
        "quit Ollama from the menu bar, run `launchctl setenv LLAMA_ARG_CACHE_RAM 512` in a " +
        "terminal, then open Ollama again." + MAC_FORGETS
      )
    case "launchd":
      return (
        "run `launchctl setenv LLAMA_ARG_CACHE_RAM 512 && " +
        (unit === "homebrew.mxcl.ollama"
          ? "brew services restart ollama"
          : `launchctl kickstart -k gui/$(id -u)/${unit}`) +
        "` in a terminal." + MAC_FORGETS
      )
    case "systemd":
      return (
        `run \`sudo systemctl edit ${unit}\`, add \`Environment="LLAMA_ARG_CACHE_RAM=512"\` ` +
        `under \`[Service]\`, save, then run \`sudo systemctl restart ${unit}\`.`
      )
    case "windows":
      return (
        "run `setx LLAMA_ARG_CACHE_RAM 512`, quit Ollama (from its tray icon, or Ctrl+C where " +
        "`ollama serve` runs), then start it again from the Start menu or a new terminal."
      )
    case "terminal":
      return (
        (/^(Darwin|macOS)/.test(host.host)
          ? "Ollama was started from a terminal, which `launchctl setenv` does not reach. "
          : "Ollama was started from a terminal. ") +
        "Stop it (Ctrl+C in that terminal) and start it with " +
        "`LLAMA_ARG_CACHE_RAM=512 ollama serve`. To keep the setting, add " +
        "`export LLAMA_ARG_CACHE_RAM=512` to your shell profile."
      )
    default:
      return "set LLAMA_ARG_CACHE_RAM=512 where Ollama is started, then restart Ollama."
  }
}

/** The banner line for a model server whose prompt cache can fill the machine, or null. */
export function promptCacheNotice(host: HostVerdict | undefined): string | null {
  if (!host?.prompt_cache_unbounded) return null
  const fix = promptCacheFix(host)
  const lead =
    "Ollama has no limit on the old prompts it keeps in memory: up to 8 GB, which slows or " +
    "crashes a 16 GB machine. Luminary unloads the model when it grows too large."
  // The terminal fix opens on its own sentence; the others continue "To fix it, ...".
  const steps = host.ollama_launch === "terminal" ? ` ${fix}` : ` To fix it, ${fix}`
  return `${lead}${steps} This notice clears once Ollama restarts with the limit.`
}

/**
 * The banner line for a host that cannot run a local model, or null. Built from
 * the routing report's refused rows, not the mode.
 */
/**
 * Which local-model warning to show, if any. None on a refused host: the host
 * notice names the cause, and a download offer there sells gigabytes the app
 * then declines to run.
 */
export function localModelNotice(
  llm: { mode?: string; processing_mode?: string; ollama_reachable?: boolean } | undefined,
  host: HostVerdict | undefined,
): "model-missing" | "server-down" | null {
  if (host?.supported === false) return null
  if (llm?.mode !== "private" || llm.processing_mode !== "unavailable") return null
  // Up-but-no-model reads as "unavailable" too; tell them apart so the fix offered is right.
  return llm.ollama_reachable === false ? "server-down" : "model-missing"
}

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

/** Below 1 and above 0: the model is split between the graphics card and the processor (#156). */
export function isSplit(host: HostVerdict | undefined): boolean {
  const share = host?.gpu_share
  return host?.supported === true && share != null && share > 0 && share < 1
}

/**
 * The banner line for a model split between card and processor, or null. A split is
 * supported, only slower (#156), so it names what runs locally and is slowed, and
 * what Cloud mode would cost. Null in Cloud mode, which already runs that work with
 * the key, and until the routing report says what runs here.
 */
export function splitNotice(
  host: HostVerdict | undefined,
  routing: RoutingResponse | undefined,
): string | null {
  if (!isSplit(host) || !routing || engineMode(routing.mode).id === "cloud") return null
  const slowed = routing.work.filter((w) => w.on_device && !w.refused_reason)
  if (slowed.length === 0) return null
  const pct = Math.floor((host?.gpu_share ?? 0) * 100)
  const labels = joinLabels(slowed.map((w) => w.label.toLowerCase()))
  return (
    `The local model does not fit on this graphics card: ${pct}% of it runs on the card and ` +
    `the rest on the processor, so ${labels} will be slower. Cloud mode is faster: it uses ` +
    "your API key, and your provider charges for each request. Change it in Settings."
  )
}
