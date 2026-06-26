// DocumentTopics -- a document's study topics (chapters, from its authored structure or an LLM
// outline when messy) plus a SEARCH over all its sub-sections for drill-down study. Front/back-matter
// (index, copyright, publisher) is filtered. Each studyable topic offers flashcard review or teach-back.

import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ListTree, Loader2, MessageSquare, Play, Search, Sparkles } from "lucide-react"

import { apiGet } from "@/lib/apiClient"

interface TopicItem {
  title: string
  level: number
  section_id: string | null
  page_start: number | null
}
interface DocumentTopics {
  document_id: string
  title: string
  source: "sections" | "outline"
  topics: TopicItem[]
}

type SectionAction = (sectionId: string, sectionHeading: string) => void

function SectionActions({
  sectionId,
  title,
  onStudySection,
  onTeachbackSection,
}: {
  sectionId: string
  title: string
  onStudySection?: SectionAction
  onTeachbackSection?: SectionAction
}) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {onStudySection && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onStudySection(sectionId, title)
          }}
          title="Flashcard review"
          className="rounded p-1 text-muted-foreground/60 hover:bg-blue-500/10 hover:text-blue-600"
        >
          <Play size={13} />
        </button>
      )}
      {onTeachbackSection && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onTeachbackSection(sectionId, title)
          }}
          title="Teach-back -- explain it in your own words"
          className="rounded p-1 text-muted-foreground/60 hover:bg-violet-500/10 hover:text-violet-600"
        >
          <MessageSquare size={13} />
        </button>
      )}
    </span>
  )
}

export function DocumentTopics({
  documentId,
  onStudySection,
  onTeachbackSection,
}: {
  documentId: string
  onStudySection?: SectionAction
  onTeachbackSection?: SectionAction
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["doc-topics", documentId],
    queryFn: () => apiGet<DocumentTopics>(`/study/topics/${documentId}`),
    staleTime: 5 * 60_000,
  })

  // sub-section drill-down search
  const [input, setInput] = useState("")
  const [q, setQ] = useState("")
  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 250)
    return () => clearTimeout(t)
  }, [input])
  const { data: subs, isFetching: subsLoading } = useQuery({
    queryKey: ["doc-sections", documentId, q],
    queryFn: () =>
      apiGet<TopicItem[]>(`/study/sections/${documentId}`, { q: q || undefined, limit: 60 }),
    enabled: q.length >= 2,
  })

  return (
    <div className="mb-8 rounded-xl border border-border bg-card/40 p-5">
      <div className="mb-3 flex items-center gap-2">
        <ListTree size={18} className="text-primary" />
        <h2 className="text-lg font-semibold text-foreground">Study topics</h2>
        {data && (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
            title={
              data.source === "outline"
                ? "Heading structure was messy; Lumen outlined the topics from the content"
                : "Taken from the document's own headings"
            }
          >
            {data.source === "outline" ? (
              <>
                <Sparkles size={11} /> outlined by Lumen
              </>
            ) : (
              "from headings"
            )}
            {" · "}
            {data.topics.length}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 size={15} className="animate-spin" />
          Extracting topics… (messy docs are outlined by Lumen, which can take a few seconds)
        </div>
      ) : isError ? (
        <div className="py-4 text-sm text-red-500">Couldn't load topics for this document.</div>
      ) : !data || data.topics.length === 0 ? (
        <div className="py-4 text-sm text-muted-foreground">
          No study topics found for this document.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {data.topics.map((t, i) => (
            <div
              key={t.section_id ?? `o-${i}`}
              className="flex items-center gap-2 rounded-md border border-border/60 px-3 py-2 text-sm"
            >
              <span className="text-xs tabular-nums text-muted-foreground">{i + 1}.</span>
              <span className="flex-1 text-foreground/90">{t.title}</span>
              {t.section_id ? (
                <SectionActions
                  sectionId={t.section_id}
                  title={t.title}
                  onStudySection={onStudySection}
                  onTeachbackSection={onTeachbackSection}
                />
              ) : (
                <span
                  className="text-[10px] text-muted-foreground/50"
                  title="Outlined topic with no section to study"
                >
                  outline
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* drill-down: search any sub-section (e.g. "Hardware Faults" under a chapter) */}
      <div className="mt-5 border-t border-border/60 pt-4">
        <div className="relative max-w-md">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search a sub-section to study (e.g. “replication”)…"
            className="w-full rounded-md border border-border bg-background py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        {q.length >= 2 && (
          <div className="mt-2">
            {subsLoading ? (
              <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
                <Loader2 size={14} className="animate-spin" /> Searching…
              </div>
            ) : !subs || subs.length === 0 ? (
              <div className="py-2 text-sm text-muted-foreground">No sub-sections match “{q}”.</div>
            ) : (
              <div className="flex flex-col divide-y divide-border/50 rounded-md border border-border/60">
                {subs.map((s) => (
                  <div
                    key={s.section_id ?? s.title}
                    className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                  >
                    <span className="truncate text-foreground/90">{s.title}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      {s.page_start ? (
                        <span className="text-xs text-muted-foreground">p.{s.page_start}</span>
                      ) : null}
                      {s.section_id && (
                        <SectionActions
                          sectionId={s.section_id}
                          title={s.title}
                          onStudySection={onStudySection}
                          onTeachbackSection={onTeachbackSection}
                        />
                      )}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
