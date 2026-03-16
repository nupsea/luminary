/**
 * ExplanationSheet — right-side sliding panel that streams an explanation.
 *
 * Calls POST /explain with SSE and streams tokens into a pre element.
 */

import { Loader2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import type { ExplainMode } from "./FloatingToolbar"
import { MarkdownRenderer } from "./MarkdownRenderer"

import { API_BASE } from "@/lib/config"

const MODE_LABELS: Record<ExplainMode | "formal", string> = {
  plain: "Explanation",
  eli5: "ELI5",
  analogy: "Analogy",
  formal: "Formal definition",
}

interface ExplanationSheetProps {
  open: boolean
  text: string
  documentId: string
  mode: ExplainMode
  onClose: () => void
}

export function ExplanationSheet({
  open,
  text,
  documentId,
  mode,
  onClose,
}: ExplanationSheetProps) {
  const [content, setContent] = useState("")
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  // Stream explanation when the sheet opens (or text/mode changes)
  useEffect(() => {
    if (!open || !text) return

    // Abort any in-flight request
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setContent("")
    setLoading(true)

    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/explain`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, document_id: documentId, mode }),
          signal: controller.signal,
        })
        if (!res.ok || !res.body) {
          setLoading(false)
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
      } catch (err) {
        if ((err as Error).name !== "AbortError") setLoading(false)
      }
    })()

    return () => {
      controller.abort()
    }
  }, [open, text, documentId, mode])

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />

      {/* Sheet */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-[400px] flex-col border-l border-border bg-background shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <p className="text-xs text-muted-foreground">{MODE_LABELS[mode]}</p>
            <p className="line-clamp-1 text-sm font-medium text-foreground">&quot;{text}&quot;</p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-4">
          {loading && !content ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              Generating explanation...
            </div>
          ) : (
            <div>
              <MarkdownRenderer>{content}</MarkdownRenderer>
              {loading && <span className="animate-pulse text-foreground">▍</span>}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
