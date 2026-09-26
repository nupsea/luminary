// A failure the user can send to the developer, any way they choose.
//
// The backend redacts the report and opens it as a text file in the user's own editor,
// so they read exactly what they send. Luminary itself never sends anything.

import { useState } from "react"
import { Check, Copy, Loader2, MessageSquareWarning } from "lucide-react"
import { toast } from "sonner"

import { apiPost } from "@/lib/apiClient"

interface OpenedReport {
  text: string
  path: string | null
  opened: boolean
}

export function ReportProblem({ problem, detail }: { problem: string; detail?: string }) {
  const [report, setReport] = useState<OpenedReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  async function open() {
    setLoading(true)
    try {
      setReport(await apiPost<OpenedReport>("/setup/report/open", { problem, detail: detail ?? "" }))
    } catch {
      toast.error("Couldn't put the report together. Is Luminary still running?")
    } finally {
      setLoading(false)
    }
  }

  async function copy() {
    if (!report) return
    try {
      await navigator.clipboard.writeText(report.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Couldn't copy. Select the text and copy it yourself.")
    }
  }

  const trigger = (
    <button
      type="button"
      onClick={() => void open()}
      disabled={loading}
      className="inline-flex items-center gap-1.5 self-start text-xs font-medium text-foreground underline underline-offset-2 hover:text-primary disabled:opacity-60"
    >
      {loading ? <Loader2 size={13} className="animate-spin" /> : <MessageSquareWarning size={13} />}
      {report ? "Open the report again" : "Report this problem"}
    </button>
  )

  if (!report) return trigger

  if (report.opened) {
    return (
      <div className="mt-1 space-y-1.5 rounded-md border border-border bg-muted/30 p-2.5 text-xs text-muted-foreground">
        <p>
          The report is open in your text editor. Read it, delete anything you would rather not
          share, and send it any way you like: the file says where. Luminary does not send it.
        </p>
        {report.path && (
          <p>
            Saved as <span className="break-all font-mono text-foreground">{report.path}</span>
          </p>
        )}
        {trigger}
      </div>
    )
  }

  return (
    <div className="mt-1 space-y-2 rounded-md border border-border bg-muted/30 p-2.5">
      <p className="text-xs text-muted-foreground">
        Couldn't open a text editor, so here is the report. Read it, delete anything you would
        rather not share, then copy it and send it any way you like: the text says where.
        {report.path && (
          <>
            {" "}It is also saved as{" "}
            <span className="break-all font-mono text-foreground">{report.path}</span>.
          </>
        )}
      </p>
      <textarea
        value={report.text}
        onChange={(e) => setReport({ ...report, text: e.target.value })}
        rows={10}
        spellCheck={false}
        aria-label="Problem report"
        className="w-full resize-y rounded-md border border-border bg-background p-2 font-mono text-[11px] leading-relaxed text-foreground"
      />
      <button
        type="button"
        onClick={() => void copy()}
        className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-foreground hover:bg-accent"
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  )
}
