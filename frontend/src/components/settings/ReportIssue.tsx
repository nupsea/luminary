// Raising an issue with the environment already filled in.
//
// Reports arrived without the information needed to reproduce them, and asking
// for it cost a round trip every time (nupsea/luminary#41). The block comes
// from the backend rather than the desktop shell: the UI is served from the
// backend's own origin, where Tauri IPC is not granted, and a browser or Docker
// install has no shell to ask.

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Check, Copy, ExternalLink } from "lucide-react"
import { toast } from "sonner"

import { apiGet } from "@/lib/apiClient"

const REPO = "nupsea/luminary"

const fetchReport = () => apiGet<{ environment: string }>("/setup/report")

function issueUrl(environment: string): string {
  const params = new URLSearchParams({
    template: "bug_report.yml",
    title: "[Bug]: ",
    env_info: environment,
  })
  return `https://github.com/${REPO}/issues/new?${params.toString()}`
}

export function ReportIssue() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["setup", "report"],
    queryFn: fetchReport,
    staleTime: 60_000,
  })
  const [copied, setCopied] = useState(false)

  async function copy() {
    if (!data) return
    try {
      await navigator.clipboard.writeText(data.environment)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Couldn't copy — select the text and copy it manually.")
    }
  }

  if (isLoading) return <div className="h-28 animate-pulse rounded-md bg-muted" />
  if (isError || !data) {
    return (
      <p className="text-xs text-muted-foreground">
        Couldn't read the environment details. You can still open an issue at{" "}
        <a
          href={`https://github.com/${REPO}/issues/new/choose`}
          target="_blank"
          rel="noreferrer"
          className="underline underline-offset-2"
        >
          github.com/{REPO}
        </a>
        .
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <pre className="max-h-40 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
        {data.environment}
      </pre>
      <div className="flex flex-wrap items-center gap-2">
        <a
          href={issueUrl(data.environment)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <ExternalLink size={14} /> Report an issue
        </a>
        <button
          onClick={() => void copy()}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-foreground hover:bg-accent"
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy details"}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        Opens a prefilled form on GitHub — nothing is sent until you press Submit there. Your
        home folder and account name are replaced before this is shown.
      </p>
    </div>
  )
}
