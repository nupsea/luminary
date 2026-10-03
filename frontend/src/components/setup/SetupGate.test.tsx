import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { SetupGate } from "./SetupGate"
import { ModelSuggestions } from "./ModelSuggestions"
import { failureSummary, type Component, type StartupPhase, type StartupStatus } from "@/lib/setupApi"

function phase(key: string, label: string, state: StartupPhase["state"], detail = "", required = false): StartupPhase {
  return { key, label, required, state, detail, completed_bytes: 0, total_bytes: 0, percent: null }
}

function component(id: string, label: string, over: Partial<Component> = {}): Component {
  return {
    id,
    label,
    description: `${label} description`,
    kind: "hf_model",
    ref: id,
    size_bytes: 1_000_000,
    licence: "x",
    default: false,
    enables: [],
    installed: false,
    offered: true,
    recommended: false,
    advice: "",
    installable: true,
    ...over,
  }
}

// The company-laptop screen from 0.13.3: an inspecting proxy broke the embedder
// download, the host has no GPU, and the optional encoders are not installed.
const phases = [
  phase("db", "Preparing your library", "ready", "", true),
  phase("embedder", "Learning to read your documents", "failed", "Your network checks secure connections.", true),
  phase("chat_model", "Chat and flashcard model", "unavailable", "This system isn't supported."),
  phase("vision_model", "Figure and diagram reading", "unavailable", "This system isn't supported."),
  phase("ner", "Concept extraction", "missing", "urchade/gliner_multi_pii-v1"),
  phase("reranker", "Answer ranking", "missing", "cross-encoder/ms-marco-MiniLM-L-12-v2"),
]

const components = [
  component("chat_model", "Chat model", { kind: "ollama_model", offered: false, advice: "No GPU." }),
  component("vision_model", "Vision model", { kind: "ollama_model", offered: false, advice: "No GPU." }),
  component("ner", "Concept extraction", { advice: "Optional: a large model." }),
  component("reranker", "Answer ranking", { recommended: true, advice: "Recommended for every computer." }),
]

function render(node: React.ReactNode, shown = components, shownPhases = phases) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const status: StartupStatus = {
    status: "degraded",
    ready: false,
    usable: true,
    blocking: true,
    failed: ["embedder"],
    missing: ["ner", "reranker"],
    offline: false,
    elapsed_seconds: 1,
    phases: shownPhases,
    version: "0.13.4",
  }
  qc.setQueryData(["setup", "status"], status)
  qc.setQueryData(["setup", "components"], shown)
  return renderToStaticMarkup(<QueryClientProvider client={qc}>{node}</QueryClientProvider>)
}

const count = (html: string, text: string) => html.split(text).length - 1

describe("SetupGate", () => {
  it("offers one problem report for the whole screen", () => {
    expect(count(render(<SetupGate>app</SetupGate>), "Report this problem")).toBe(1)
  })

  it("says a refused local model is not on this computer, and offers no install", () => {
    const html = render(<SetupGate>app</SetupGate>)
    expect(count(html, "Not on this computer")).toBe(2)
    expect(html).not.toContain("Install chat model")
    expect(html).not.toContain("Install vision model")
  })

  it("marks what Luminary recommends and offers the rest as optional", () => {
    const html = render(<SetupGate>app</SetupGate>)
    expect(html).toContain("Recommended for every computer.")
    expect(html).toContain("Install answer ranking")
    expect(html).toContain("Install concept extraction")
  })
})

describe("SetupGate on a computer that can hold more than one chat model", () => {
  const choice = (model: string, recommended: boolean) => ({
    model,
    size_bytes: 3_000_000_000,
    reads_figures: !recommended,
    recommended,
    selected: recommended,
    installed: false,
    trade_off: `${model} trade-off`,
  })
  const chat = component("chat_model", "Chat model", {
    kind: "ollama_model",
    recommended: true,
    choices: [choice("ollama/qwen2.5:14b-instruct", true), choice("ollama/qwen3.5:4b", false)],
  })
  const missingChat = [
    phase("db", "Preparing your library", "ready", "", true),
    phase("chat_model", "Chat and flashcard model", "missing", "qwen2.5:14b-instruct"),
  ]

  it("offers every model with its trade-off and lets the user pick, never one fixed download", () => {
    const html = render(<SetupGate>app</SetupGate>, [chat], missingChat)
    expect(html).toContain("qwen2.5:14b-instruct trade-off")
    expect(html).toContain("qwen3.5:4b trade-off")
    expect(count(html, "Recommended for this computer")).toBe(1)
    expect(count(html, "Install and use")).toBe(2)
    expect(html).not.toContain("Install chat model")
  })
})

describe("a tool Luminary cannot install", () => {
  it("offers a re-check instead of an install button that can only fail", () => {
    const ffmpeg = component("ffmpeg", "Audio and video support", {
      kind: "tool",
      installable: false,
      advice: "Install it with `brew install ffmpeg`.",
    })
    const html = render(<ModelSuggestions />, [{ ...ffmpeg, recommended: true }])
    expect(html).toContain("Check again")
    expect(html).not.toContain("Install audio and video support")
  })
})

describe("failureSummary", () => {
  it("lists every failed step and nothing else", () => {
    expect(failureSummary(phases)).toBe(
      "Learning to read your documents: Your network checks secure connections.",
    )
  })
})

describe("ModelSuggestions", () => {
  it("suggests only what is recommended, offered and not installed", () => {
    const html = render(<ModelSuggestions />)
    expect(html).toContain("Answer ranking")
    expect(html).not.toContain("Concept extraction")
    expect(html).not.toContain("Chat model")
  })
})
