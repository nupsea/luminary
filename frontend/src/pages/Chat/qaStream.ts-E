// SSE client for the /qa endpoint. Parses `data: {...}` events and dispatches
// typed callbacks; the page owns React state and persistence side-effects.

import { API_BASE } from "@/lib/config"

import type {
  AnyCardData,
  Citation,
  Confidence,
  TransparencyInfo,
  WebSource,
} from "./types"
import type { SourceCitation } from "@/components/SourceCitationChips"

export interface QaStreamRequest {
  question: string
  document_ids: string[] | null
  scope: "single" | "all"
  model: string | null
  messages?: { role: "user" | "assistant"; content: string }[]
  web_enabled: boolean
}

export interface QaDoneEvent {
  not_found: boolean
  finalAnswer: string | undefined
  citations: Citation[]
  confidence: Confidence
  image_ids: string[]
  web_sources: WebSource[]
  source_citations: SourceCitation[]
  web_calls_used: number | undefined
}

export interface QaStreamHandlers {
  onCard: (card: AnyCardData) => void
  onToken: (token: string) => void
  onTransparency: (transparency: TransparencyInfo) => void
  onError: (errorCode: string, fallback: string) => void
  onDone: (done: QaDoneEvent) => void
}

export async function streamQa(req: QaStreamRequest, handlers: QaStreamHandlers): Promise<void> {
  // SSE stream: we read res.body.getReader() token-by-token, so apiClient's
  // JSON-decoding path doesn't apply.
  // eslint-disable-next-line no-restricted-syntax
  const res = await fetch(`${API_BASE}/qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok || !res.body) throw new Error("QA request failed")

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
      try {
        const payload = JSON.parse(line.slice(6)) as Record<string, unknown>

        if (payload["card"] !== undefined) {
          handlers.onCard(payload["card"] as AnyCardData)
        }

        if (typeof payload["token"] === "string") {
          handlers.onToken(payload["token"] as string)
        }

        // transparency event arrives before 'done' — silently omit if malformed
        if (payload["type"] === "transparency") {
          try {
            const transparency: TransparencyInfo = {
              confidence_level: payload["confidence_level"] as string,
              strategy_used: payload["strategy_used"] as string,
              chunk_count: payload["chunk_count"] as number,
              section_count: payload["section_count"] as number,
              augmented: payload["augmented"] as boolean,
            }
            handlers.onTransparency(transparency)
          } catch {
            /* malformed transparency event */
          }
        }

        if (typeof payload["error"] === "string") {
          const errorCode = payload["error"] as string
          const fallbackMsg = (payload["message"] as string | undefined) ?? "An error occurred."
          handlers.onError(errorCode, fallbackMsg)
          return
        }

        if (payload["done"] === true) {
          handlers.onDone({
            not_found: payload["not_found"] === true,
            finalAnswer: typeof payload["answer"] === "string" ? (payload["answer"] as string) : undefined,
            citations: (payload["citations"] as Citation[] | undefined) ?? [],
            confidence: (payload["confidence"] as Confidence | undefined) ?? "low",
            image_ids: (payload["image_ids"] as string[] | undefined) ?? [],
            web_sources: (payload["web_sources"] as WebSource[] | undefined) ?? [],
            source_citations: (payload["source_citations"] as SourceCitation[] | undefined) ?? [],
            web_calls_used: payload["web_calls_used"] as number | undefined,
          })
        }
      } catch {
        /* skip malformed SSE event */
      }
    }
  }
}

export function buildErrorMessage(errorCode: string, fallback: string): string {
  if (errorCode === "llm_unavailable") return "Ollama is not running. Start it with: ollama serve"
  if (errorCode === "no_context") return "No relevant content found. Make sure at least one document has been ingested."
  return fallback
}
