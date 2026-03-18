import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { Loader2 } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { API_BASE } from "@/lib/config"
import type { AnnotationItem, SectionContentItem } from "./types"

const HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "bg-yellow-200/60 dark:bg-yellow-500/30",
  green: "bg-green-200/60 dark:bg-green-500/30",
  blue: "bg-blue-200/60 dark:bg-blue-500/30",
  pink: "bg-pink-200/60 dark:bg-pink-500/30",
}

async function fetchSectionContent(documentId: string): Promise<SectionContentItem[]> {
  const res = await fetch(`${API_BASE}/sections/${documentId}/content`)
  if (!res.ok) throw new Error("Failed to fetch section content")
  return res.json() as Promise<SectionContentItem[]>
}

/** Apply highlight marks to plain text by matching annotation selected_text substrings. */
function applyHighlights(content: string, annotations: AnnotationItem[]): string {
  if (annotations.length === 0) return content

  // Find all occurrences, sort by position, merge overlaps
  const marks: { start: number; end: number; color: string }[] = []
  for (const ann of annotations) {
    const idx = content.indexOf(ann.selected_text)
    if (idx >= 0) {
      marks.push({ start: idx, end: idx + ann.selected_text.length, color: ann.color })
    }
  }
  if (marks.length === 0) return content

  marks.sort((a, b) => a.start - b.start)

  // Build result with <mark> tags
  let result = ""
  let cursor = 0
  for (const m of marks) {
    if (m.start < cursor) continue // skip overlapping
    result += content.slice(cursor, m.start)
    const cls = HIGHLIGHT_COLORS[m.color] ?? HIGHLIGHT_COLORS.yellow
    result += `<mark class="${cls} rounded-sm px-0.5">${content.slice(m.start, m.end)}</mark>`
    cursor = m.end
  }
  result += content.slice(cursor)
  return result
}

interface ReadViewProps {
  documentId: string
  initialSectionId?: string | null
  annotations?: AnnotationItem[]
}

export function ReadView({ documentId, initialSectionId, annotations = [] }: ReadViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const { data: sections, isLoading, error } = useQuery({
    queryKey: ["section-content", documentId],
    queryFn: () => fetchSectionContent(documentId),
  })

  useEffect(() => {
    if (!initialSectionId || !sections) return
    const el = document.getElementById(`read-sec-${initialSectionId}`)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [initialSectionId, sections])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <p className="px-6 py-4 text-sm text-destructive">
        Failed to load document content.
      </p>
    )
  }

  if (!sections || sections.length === 0) {
    return (
      <p className="px-6 py-4 text-sm text-muted-foreground">
        No content available.
      </p>
    )
  }

  const HeadingTag = (level: number) => {
    if (level <= 1) return "h2"
    if (level === 2) return "h3"
    if (level === 3) return "h4"
    return "h5"
  }

  return (
    <div ref={containerRef} className="flex-1 overflow-auto px-6 py-4">
      {sections.map((section) => {
        const Tag = HeadingTag(section.level)
        const sectionAnnotations = annotations.filter((a) => a.section_id === section.section_id)
        const highlighted = applyHighlights(section.content, sectionAnnotations)
        const hasHighlights = highlighted !== section.content
        return (
          <div
            key={section.section_id}
            id={`read-sec-${section.section_id}`}
            data-section-id={section.section_id}
            className="mb-8 pb-6 border-b border-border last:border-b-0"
          >
            <Tag className="mb-2 font-semibold text-foreground">
              {section.heading || "(Untitled section)"}
            </Tag>
            {hasHighlights ? (
              <div
                className="prose prose-sm dark:prose-invert max-w-none"
                dangerouslySetInnerHTML={{ __html: highlighted }}
              />
            ) : (
              <MarkdownRenderer>{section.content}</MarkdownRenderer>
            )}
          </div>
        )
      })}
    </div>
  )
}
