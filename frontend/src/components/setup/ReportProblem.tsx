// A failure the user can send to the developer in two clicks, log included.
//
// Email only: a report can come from a work computer, so it never goes anywhere public.
// The backend redacts it before it is shown and the user can still edit it.

import { useState } from "react"
import { Check, Copy, Loader2, Mail, MessageSquareWarning } from "lucide-react"
import { toast } from "sonner"

import { apiGet } from "@/lib/apiClient"
import { compose, emailUrl, type ProblemReport } from "@/lib/problemReport"

export function ReportProblem({ problem, detail }: { problem: string; detail?: string }) {
  const [text, setText] = useState<string | null>(null)
  const [email, setEmail] = useState("")
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  async function open() {
    setLoading(true)
    try {
      const params = new URLSearchParams({ problem, detail: detail ?? "" })
      const report = await apiGet<ProblemReport>(`/setup/report?${params.toString()}`)
      setEmail(report.email)
      setText(compose(report))
    } catch {
      toast.error("Couldn't put the report together. Is Luminary still running?")
    } finally {
      setLoading(false)
    }
  }

  async function copy(): Promise<boolean> {
    if (text === null) return false
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      return false
    }
  }

  async function send(url: string) {
    await copy()
    window.open(url, "_blank", "noopener")
  }

  if (text === null) {
    return (
      <button
        type="button"
        onClick={() => void open()}
        disabled={loading}
        className="inline-flex items-center gap-1.5 self-start text-xs font-medium text-foreground underline underline-offset-2 hover:text-primary disabled:opacity-60"
      >
        {loading ? <Loader2 size={13} className="animate-spin" /> : <MessageSquareWarning size={13} />}
        Report this problem
      </button>
    )
  }

  return (
    <div className="mt-1 space-y-2 rounded-md border border-border bg-muted/30 p-2.5">
      <p className="text-xs text-muted-foreground">
        Read the report before sending it, and delete anything you would rather not share.
        Names of people, computers, company networks, folders, web servers and documents, and any
        keys or email addresses, are already removed.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={8}
        spellCheck={false}
        aria-label="Problem report"
        className="w-full resize-y rounded-md border border-border bg-background p-2 font-mono text-[11px] leading-relaxed text-foreground"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void send(emailUrl(email, problem, text))}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Mail size={13} /> Email to the developer
        </button>
        <button
          type="button"
          onClick={() =>
            void copy().then((ok) => {
              if (!ok) {
                toast.error("Couldn't copy. Select the text and copy it yourself.")
                return
              }
              setCopied(true)
              setTimeout(() => setCopied(false), 2000)
            })
          }
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-foreground hover:bg-accent"
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        The report goes privately to {email}, and only when you press Send in your mail app. On a
        work computer that app may use your work account: to send from a personal address
        instead, press Copy and paste the report into an email to {email}.
      </p>
    </div>
  )
}
