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

function render(node: React.ReactNode) {
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
    phases,
    version: "0.13.4",
  }
  qc.setQueryData(["setup", "status"], status)
  qc.setQueryData(["setup", "components"], components)
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
