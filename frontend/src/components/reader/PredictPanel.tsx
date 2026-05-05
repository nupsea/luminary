import { Check, Loader2, Terminal, X } from "lucide-react"
import { useRef, useState } from "react"

import { API_BASE } from "@/lib/config"

interface CodeExecuteResult {
  stdout: string
  stderr: string
  exit_code: number
  elapsed_ms: number
  prediction_correct: boolean | null
  prediction_diff: string | null
}

/** Section preview contains a fenced code block (newline-delimited ``` fence). */
export function hasCodeFence(preview: string): boolean {
  return /^```\w*/m.test(preview) && preview.includes("\n")
}

function extractCodeFromPreview(preview: string): string {
  const match = /```[\w]*\n([\s\S]*?)(?:```|$)/.exec(preview)
  const code = match ? match[1] : preview
  return code.slice(0, 2000)
}

interface PredictPanelProps {
  sectionId: string
  documentId: string
  preview: string
}

export function PredictPanel({ sectionId: _sectionId, documentId, preview }: PredictPanelProps) {
  const [predictOpen, setPredictOpen] = useState(false)
  const [expectedOutput, setExpectedOutput] = useState("")
  const [isRunning, setIsRunning] = useState(false)
  const [runResult, setRunResult] = useState<CodeExecuteResult | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [createCardOpen, setCreateCardOpen] = useState(false)
  const [createSuccess, setCreateSuccess] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const code = extractCodeFromPreview(preview)

  async function handleRunAndCompare() {
    setIsRunning(true)
    setRunError(null)
    setRunResult(null)
    setCreateCardOpen(false)
    setCreateSuccess(false)
    setCreateError(null)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const resp = await fetch(`${API_BASE}/code/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          code,
          language: "python",
          expected_output: expectedOutput.trim() !== "" ? expectedOutput : undefined,
          document_id: documentId,
        }),
      })
      if (!resp.ok) {
        const body = (await resp.json()) as { detail?: string }
        setRunError(body.detail ?? `Execution failed (HTTP ${resp.status})`)
        return
      }
      const data = (await resp.json()) as CodeExecuteResult
      setRunResult(data)
    } catch (err) {
      if ((err as { name?: string }).name !== "AbortError") {
        setRunError("Execution failed. Check your connection.")
      }
    } finally {
      setIsRunning(false)
      abortRef.current = null
    }
  }

  function handleKill() {
    abortRef.current?.abort()
    setIsRunning(false)
    setRunError("Execution cancelled.")
  }

  async function handleCreateFlashcard() {
    if (!runResult) return
    setCreateError(null)
    const question = `What does this code output?\n\n\`\`\`python\n${code.slice(0, 500)}\n\`\`\``
    const answer = `Correct output:\n${runResult.stdout}${runResult.prediction_diff ? `\n\nDiff:\n${runResult.prediction_diff}` : ""}`
    try {
      const resp = await fetch(`${API_BASE}/flashcards/create-trace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          answer,
          source_excerpt: code.slice(0, 500),
          document_id: documentId,
        }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setCreateSuccess(true)
      setCreateCardOpen(false)
    } catch {
      setCreateError("Failed to create flashcard. Please try again.")
    }
  }

  if (!predictOpen) {
    return (
      <button
        onClick={() => setPredictOpen(true)}
        title="Predict the output before running"
        className="mt-1.5 flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary"
      >
        <Terminal size={10} />
        Predict
      </button>
    )
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-md border border-border bg-muted/30 p-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground">What will this output?</span>
        <button
          onClick={() => { setPredictOpen(false); setRunResult(null); setRunError(null); setCreateCardOpen(false); setCreateSuccess(false) }}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Close predict panel"
        >
          <X size={12} />
        </button>
      </div>

      <textarea
        value={expectedOutput}
        onChange={(e) => setExpectedOutput(e.target.value)}
        placeholder="Type your prediction..."
        rows={2}
        className="w-full resize-none rounded border border-border bg-background px-2 py-1 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      />

      <div className="flex gap-2">
        <button
          onClick={() => void handleRunAndCompare()}
          disabled={isRunning}
          className="flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isRunning && <Loader2 size={10} className="animate-spin" />}
          {isRunning ? "Running..." : "Run and Compare"}
        </button>
        {isRunning && (
          <button
            onClick={handleKill}
            className="rounded border border-destructive px-2.5 py-1 text-xs text-destructive hover:bg-destructive/10"
          >
            Kill
          </button>
        )}
      </div>

      {runError && (
        <div className="rounded border border-destructive/40 bg-destructive/10 px-2 py-1 text-xs text-destructive">
          {runError}
          <button
            onClick={() => void handleRunAndCompare()}
            className="ml-2 underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {runResult && (
        <div className="flex flex-col gap-1.5">
          <div>
            <span className="text-xs text-muted-foreground">Output:</span>
            <pre className="mt-0.5 overflow-auto rounded border border-border bg-background px-2 py-1 font-mono text-xs text-foreground">
              {runResult.stdout || <em className="text-muted-foreground">(no output)</em>}
            </pre>
          </div>

          {runResult.stderr && (
            <div>
              <span className="text-xs text-muted-foreground">stderr:</span>
              <pre className="mt-0.5 overflow-auto rounded border border-destructive/40 bg-destructive/5 px-2 py-1 font-mono text-xs text-destructive">
                {runResult.stderr}
              </pre>
            </div>
          )}

          {runResult.prediction_correct !== null && (
            <>
              {runResult.prediction_correct ? (
                <div className="flex items-center gap-1.5 rounded border border-green-400/40 bg-green-50 px-2 py-1 text-xs text-green-700">
                  <Check size={12} />
                  Your prediction was correct!
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <div className="rounded border border-amber-400/40 bg-amber-50 px-2 py-1 text-xs text-amber-800">
                    Your prediction was wrong.
                    {runResult.prediction_diff && (
                      <pre className="mt-1 overflow-auto font-mono text-xs text-amber-900">
                        {runResult.prediction_diff}
                      </pre>
                    )}
                  </div>

                  {!createSuccess && (
                    <div className="flex flex-col gap-1">
                      {!createCardOpen ? (
                        <button
                          onClick={() => setCreateCardOpen(true)}
                          className="self-start rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-primary hover:text-primary"
                        >
                          Create flashcard from this mistake?
                        </button>
                      ) : (
                        <div className="flex flex-col gap-1">
                          {createError && (
                            <p className="text-xs text-destructive">{createError}</p>
                          )}
                          <div className="flex gap-2">
                            <button
                              onClick={() => void handleCreateFlashcard()}
                              className="flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                            >
                              <Check size={10} />
                              Create Flashcard
                            </button>
                            <button
                              onClick={() => { setCreateCardOpen(false); setCreateError(null) }}
                              className="rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {createSuccess && (
                    <p className="text-xs text-green-700">Flashcard created!</p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {!runResult && !isRunning && !runError && (
        <p className="text-xs text-muted-foreground">
          Type your prediction and click "Run and Compare" to see the result.
        </p>
      )}
    </div>
  )
}
