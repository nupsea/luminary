/**
 * ReferencesPanel -- S138
 *
 * Shows LLM-suggested canonical web references for a document, grouped by section.
 * Renders in the DocumentReader right sidebar as the "References" tab.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, RefreshCw } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"

const API_BASE = "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SourceQuality = "official_docs" | "spec" | "wiki" | "tutorial" | "blog" | "unknown"

interface WebReferenceItem {
  id: string
  section_id: string | null
  term: string
  url: string
  title: string
  excerpt: string
  source_quality: SourceQuality
  is_llm_suggested: boolean
  created_at: string
  is_outdated: boolean
}

interface DocumentReferencesResponse {
  document_id: string
  references: WebReferenceItem[]
}

// ---------------------------------------------------------------------------
// Quality badge helpers
// ---------------------------------------------------------------------------

const QUALITY_LABEL: Record<SourceQuality, string> = {
  official_docs: "Official",
  spec: "Spec",
  wiki: "Wiki",
  tutorial: "Tutorial",
  blog: "Blog",
  unknown: "Unknown",
}

const QUALITY_CLASS: Record<SourceQuality, string> = {
  official_docs: "bg-green-100 text-green-800",
  spec: "bg-blue-100 text-blue-800",
  wiki: "bg-gray-100 text-gray-800",
  tutorial: "bg-gray-100 text-gray-700",
  blog: "bg-gray-100 text-gray-600",
  unknown: "bg-gray-100 text-gray-500",
}

function QualityBadge({ quality }: { quality: SourceQuality }) {
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${QUALITY_CLASS[quality]}`}
    >
      {QUALITY_LABEL[quality]}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Single reference row
// ---------------------------------------------------------------------------

function ReferenceRow({
  ref: item,
  documentId,
}: {
  ref: WebReferenceItem
  documentId: string
}) {
  const queryClient = useQueryClient()

  async function handleRefresh() {
    if (!item.section_id) return
    try {
      await fetch(
        `${API_BASE}/references/sections/${item.section_id}/refresh?document_id=${documentId}`,
        { method: "POST" },
      )
      void queryClient.invalidateQueries({ queryKey: ["doc-references", documentId] })
    } catch {
      // non-fatal
    }
  }

  return (
    <div className="group flex flex-col gap-0.5 rounded-md border border-border p-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex min-w-0 items-center gap-1 font-medium text-primary hover:underline"
        >
          <ExternalLink size={11} className="shrink-0" />
          <span className="truncate">{item.title}</span>
        </a>
        <div className="flex shrink-0 items-center gap-1">
          <QualityBadge quality={item.source_quality} />
          {item.is_llm_suggested && (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
              Not verified
            </span>
          )}
          {item.is_outdated && (
            <button
              onClick={() => void handleRefresh()}
              title="Re-run extraction for this section"
              className="flex items-center gap-0.5 rounded bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700 hover:bg-orange-200"
            >
              <RefreshCw size={9} />
              Outdated?
            </button>
          )}
        </div>
      </div>
      {item.term && (
        <span className="text-[11px] text-muted-foreground">
          Term: <span className="font-medium">{item.term}</span>
        </span>
      )}
      {item.excerpt && (
        <p className="text-[11px] text-muted-foreground line-clamp-2">{item.excerpt}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface ReferencesPanelProps {
  documentId: string
}

export function ReferencesPanel({ documentId }: ReferencesPanelProps) {
  const { data, isLoading, isError } = useQuery<DocumentReferencesResponse>({
    queryKey: ["doc-references", documentId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/references/documents/${documentId}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json() as Promise<DocumentReferencesResponse>
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  })

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3 p-1">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex flex-col gap-1">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ))}
      </div>
    )
  }

  // Error state
  if (isError) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        References unavailable. Please try again later.
      </div>
    )
  }

  const references = data?.references ?? []

  // Empty state
  if (references.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No references generated yet. References are extracted automatically after ingestion
        completes for technical documents.
      </p>
    )
  }

  // Group by section_id (null = document-level)
  const groups = new Map<string | null, WebReferenceItem[]>()
  for (const ref of references) {
    const key = ref.section_id
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(ref)
  }

  return (
    <div className="flex flex-col gap-4">
      {Array.from(groups.entries()).map(([sectionId, refs]) => (
        <div key={sectionId ?? "__doc_level__"} className="flex flex-col gap-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {sectionId ? `Section` : "Document-level"}
          </h4>
          {refs.map((ref) => (
            <ReferenceRow key={ref.id} ref={ref} documentId={documentId} />
          ))}
        </div>
      ))}
    </div>
  )
}
