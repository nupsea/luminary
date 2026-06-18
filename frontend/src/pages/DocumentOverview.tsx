// DocumentOverview -- "what is this document and what can I do with it"
// (docs/02-ingest-and-doc-overview.md). Replaces click-into-a-surprise-session.
// Reads GET /documents/:id/overview; Study/Generate open the Study Launcher.

import { useQuery } from "@tanstack/react-query"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, BookOpen, MessageSquare, Sparkles, Target } from "lucide-react"

import { ReferencesPanel } from "@/components/reader/ReferencesPanel"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import { launchStudy } from "@/lib/studyLauncher"
import { useAppStore } from "@/store"

interface EvidenceQuote {
  document_id: string
  quote: string
}
interface OverviewConcept {
  id: string
  label: string
  kind: string
  status: string
  mastery: number
  evidence: EvidenceQuote[]
}
interface CollectionRef {
  id: string
  name: string
  color: string
}
interface DocumentOverview {
  id: string
  title: string
  format: string
  content_type: string
  tags: string[]
  reading_progress_pct: number
  collections: CollectionRef[]
  concepts: OverviewConcept[]
}

function ActionButton({
  icon, label, onClick, primary,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  primary?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors " +
        (primary
          ? "bg-primary text-primary-foreground hover:bg-primary/90"
          : "border border-border text-foreground hover:bg-accent")
      }
    >
      {icon}
      {label}
    </button>
  )
}

export default function DocumentOverview() {
  const { id = "" } = useParams()
  const navigate = useNavigate()
  const setChatSelectedDocId = useAppStore((s) => s.setChatSelectedDocId)
  const setChatScope = useAppStore((s) => s.setChatScope)

  const { data, isLoading, isError } = useQuery({
    queryKey: ["doc-overview", id],
    queryFn: () => apiGet<DocumentOverview>(`/documents/${id}/overview`),
    enabled: Boolean(id),
  })

  function openReader() {
    navigate(`/library?doc=${id}`, { state: { from: window.location.pathname } })
  }
  function chatAbout() {
    setChatSelectedDocId(id)
    setChatScope("single")
    window.dispatchEvent(new CustomEvent("luminary:navigate", { detail: { tab: "chat" } }))
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-6">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }
  if (isError || !data) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <button onClick={() => navigate("/library")} className="mb-4 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft size={14} /> Library
        </button>
        <p className="text-sm text-red-600 dark:text-red-400">Couldn't load this document.</p>
      </div>
    )
  }

  const title = data.title
  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <button onClick={() => navigate("/library")} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft size={14} /> Library
      </button>

      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <span>{data.content_type}</span>
          <span>·</span>
          <span>{data.format}</span>
          <span>·</span>
          <span>{Math.round(data.reading_progress_pct * 100)}% read</span>
        </div>
        <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
        {data.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {data.tags.map((t) => (
              <span key={t} className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                {t}
              </span>
            ))}
          </div>
        )}
        {data.collections.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-xs text-muted-foreground">In:</span>
            {data.collections.map((c) => (
              <button
                key={c.id}
                onClick={() => navigate(`/collections/${c.id}`)}
                className="rounded-full px-2 py-0.5 text-xs"
                style={{ backgroundColor: `${c.color}22`, color: c.color }}
              >
                {c.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <ActionButton primary icon={<BookOpen size={15} />} label="Read" onClick={openReader} />
        <ActionButton
          icon={<Target size={15} />}
          label="Study this"
          onClick={() => launchStudy({ type: "doc", ref: id, label: title })}
        />
        <ActionButton
          icon={<Sparkles size={15} />}
          label="Generate questions"
          onClick={() => launchStudy({ type: "doc", ref: id, label: title })}
        />
        <ActionButton icon={<MessageSquare size={15} />} label="Chat about" onClick={chatAbout} />
      </div>

      {/* Concepts extracted */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Concepts extracted</h2>
        {data.concepts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No concepts extracted yet.</p>
        ) : (
          <ul className="space-y-2">
            {data.concepts.map((c) => (
              <li key={c.id} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <button
                    onClick={() => launchStudy({ type: "concept", ref: c.id, label: c.label })}
                    className="text-left text-sm font-medium text-foreground hover:text-primary"
                  >
                    {c.label}
                  </button>
                  <div className="flex items-center gap-2">
                    {c.status !== "confirmed" && (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                        {c.status}
                      </span>
                    )}
                    <span className="text-xs text-muted-foreground">{Math.round(c.mastery)}%</span>
                  </div>
                </div>
                {c.evidence.length > 0 && (
                  <p className="mt-1.5 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
                    "{c.evidence[0].quote}"
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* References (restored) */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">References</h2>
        <ReferencesPanel documentId={id} />
      </section>
    </div>
  )
}
