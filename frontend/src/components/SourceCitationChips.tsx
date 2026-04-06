/**
 * SourceCitationChips — S157
 *
 * Renders clickable citation chips for chat answers.  Each chip links to the
 * exact section/page in DocumentReader.  Chips fade in after the 'sources'
 * payload arrives in the SSE done event (i.e. when isStreaming is false).
 *
 * Exported pure helpers (deduplicateCitations) are tested in the companion
 * SourceCitationChips.test.ts file.
 */

import { Badge } from "@/components/ui/badge"

export interface SourceCitation {
  chunk_id: string
  document_id: string
  document_title: string
  section_id: string | null
  section_heading: string
  pdf_page_number: number | null
  section_preview_snippet: string  // S157: first 150 chars of chunk text
}

/**
 * Client-side deduplication by section_id.  When section_id is null, the
 * chunk_id is used as the dedup key (each unlinked chunk stays distinct).
 * Backend already deduplicates — this is a defensive second pass.
 */
export function deduplicateCitations(citations: SourceCitation[]): SourceCitation[] {
  const seen = new Set<string>()
  return citations.filter((c) => {
    const key = c.section_id ?? c.chunk_id
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

interface Props {
  citations: SourceCitation[]
  navigateToCitation: (c: SourceCitation) => void
}

export function SourceCitationChips({ citations, navigateToCitation }: Props) {
  const deduped = deduplicateCitations(citations)
  if (deduped.length === 0) return null

  return (
    <div className="mt-3 space-y-1 animate-in fade-in duration-300">
      <span className="text-xs font-medium text-muted-foreground">
        From {deduped.length} {deduped.length === 1 ? "source" : "sources"}
      </span>
      <div className="flex flex-wrap gap-1.5 mt-1">
        {deduped.map((c, i) => {
          const titleAbbrev = c.document_title
            ? `${c.document_title.slice(0, 20)}${c.document_title.length > 20 ? "..." : ""}`
            : "Doc"
          const headingOrSnippet = c.section_heading || c.section_preview_snippet || ""
          const headingAbbrev = headingOrSnippet
            ? ` / ${headingOrSnippet.slice(0, 30)}${headingOrSnippet.length > 30 ? "..." : ""}`
            : ""
          const pageLabel = Number(c.pdf_page_number) > 0 ? ` p.${c.pdf_page_number}` : ""
          const tooltipLines = [
            c.document_title,
            c.section_heading,
            c.section_preview_snippet,
          ]
            .filter(Boolean)
            .join("\n")

          return (
            <button
              key={i}
              onClick={() => navigateToCitation(c)}
              title={tooltipLines}
              className="inline-flex items-center"
            >
              <Badge
                variant="blue"
                className="cursor-pointer hover:opacity-80 transition-opacity"
              >
                {titleAbbrev}{headingAbbrev}{pageLabel}
              </Badge>
            </button>
          )
        })}
      </div>
    </div>
  )
}
