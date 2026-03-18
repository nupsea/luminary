import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { Loader2 } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { API_BASE } from "@/lib/config"
import type { SectionContentItem } from "./types"

async function fetchSectionContent(documentId: string): Promise<SectionContentItem[]> {
  const res = await fetch(`${API_BASE}/sections/${documentId}/content`)
  if (!res.ok) throw new Error("Failed to fetch section content")
  return res.json() as Promise<SectionContentItem[]>
}

interface ReadViewProps {
  documentId: string
  initialSectionId?: string | null
}

export function ReadView({ documentId, initialSectionId }: ReadViewProps) {
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
            <MarkdownRenderer>{section.content}</MarkdownRenderer>
          </div>
        )
      })}
    </div>
  )
}
