/**
 * ExplanationPanel -- the Explain face of the reader's docked panel.
 *
 * Calls POST /explain with SSE and streams tokens beside the passage rather
 * than over it.
 */

import { Loader2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { ExplainMode } from "@/components/FloatingToolbar"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"

import { API_BASE } from "@/lib/config"

const MODE_LABELS: Record<ExplainMode | "formal", string> = {
  plain: "Explanation",
  eli5: "ELI5",
  analogy: "Analogy",
  formal: "Formal definition",
}

interface ExplanationPanelProps {
  text: string
  documentId: string
  mode: ExplainMode
  onClose: () => void
}

export function ExplanationPanel({
  text,
  documentId,
  mode,
  onClose,
}: ExplanationPanelProps) {
  // The panel is keyed on the passage, so a new one arrives as a fresh mount
  // and these are its reset. Retrying is the only case that reuses the mount,
  // and it clears them itself.
  const [content, setContent] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!text) return

    // Abort any in-flight request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    void (async () => {
      try {
        // SSE stream: tokens arrive via res.body.getReader(); apiClient's
        // JSON path doesn't apply.
        // eslint-disable-next-line no-restricted-syntax
        const res = await fetch(`${API_BASE}/explain`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, document_id: documentId, mode }),
          signal: controller.signal,
        })
        if (!res.ok || !res.body) {
          setLoading(false)
          setError(`The explanation could not be generated (HTTP ${res.status}).`)
          return
        }
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
            if (line.startsWith("data: ")) {
              try {
                const payload = JSON.parse(line.slice(6)) as Record<string, unknown>
                if (typeof payload["token"] === "string") {
                  setLoading(false)
                  setContent((c) => c + (payload["token"] as string))
                }
                if (payload["done"] === true) {
                  setLoading(false)
                }
              } catch {
                // skip malformed SSE
              }
            }
          }
        }
        setLoading(false)
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setLoading(false)
          setError("The explanation stream stopped. Is the model running?")
        }
      }
    })()

    return () => {
      controller.abort()
    }
  }, [text, documentId, mode, attempt])

  return (
    <div data-testid="docked-explanation" className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{MODE_LABELS[mode]}</p>
          <p className="line-clamp-2 text-sm font-medium text-foreground">&quot;{text}&quot;</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close explanation"
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          <X size={16} />
        </button>
      </div>

      <div data-testid="explanation-body" className="min-h-0 flex-1 overflow-auto p-4">
        {error ? (
          <p className="text-xs text-destructive">
            {error}
            <button
              onClick={() => {
                setContent("")
                setError(null)
                setLoading(true)
                setAttempt((n) => n + 1)
              }}
              className="ml-2 underline hover:no-underline"
            >
              Retry
            </button>
          </p>
        ) : loading && !content ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            Generating explanation...
          </div>
        ) : content ? (
          <div>
            <MarkdownRenderer>{content}</MarkdownRenderer>
            {loading && <span className="animate-pulse text-foreground">&#9613;</span>}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">The model returned nothing for this passage.</p>
        )}
      </div>
    </div>
  )
}
