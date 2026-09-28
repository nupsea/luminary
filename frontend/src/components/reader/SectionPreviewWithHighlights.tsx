import { cn } from "@/lib/utils"

import type { AnnotationItem } from "./types"
import { COLOR_CLASSES } from "./highlightColors"

// FTS5 snippet() always produces plain <mark>/</mark> with no attributes; this
// strict-match strip closes the attribute-injection bypass that a lookahead-only
// approach (e.g. <mark onmouseover="...">) would leave open.
function sanitizeSnippet(html: string): string {
  return html.replace(/<(?!\/?mark>)[^>]*>/gi, "")
}

interface SectionPreviewProps {
  preview: string
  annotations: AnnotationItem[]
  sectionId: string
  searchSnippet?: string
}

export function SectionPreviewWithHighlights({ preview, annotations, sectionId, searchSnippet }: SectionPreviewProps) {
  if (searchSnippet) {
    return (
      <p
        className="mt-1 line-clamp-2 text-xs text-muted-foreground section-preview"
        dangerouslySetInnerHTML={{ __html: sanitizeSnippet(searchSnippet) }}
      />
    )
  }
  const sectionAnnotations = annotations
    .filter((a) => a.section_id === sectionId)
    .sort((a, b) => a.start_offset - b.start_offset)

  if (sectionAnnotations.length === 0) {
    return (
      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground section-preview">{preview}</p>
    )
  }

  const segments: { text: string; annotation: AnnotationItem | null }[] = []
  let cursor = 0
  for (const ann of sectionAnnotations) {
    const start = ann.start_offset
    const end = ann.end_offset
    if (start < cursor || end <= start || end > preview.length) continue
    const highlightText = preview.slice(start, end)
    if (!ann.selected_text.startsWith(highlightText.slice(0, 10))) continue
    if (start > cursor) segments.push({ text: preview.slice(cursor, start), annotation: null })
    segments.push({ text: highlightText, annotation: ann })
    cursor = end
  }
  if (cursor < preview.length) segments.push({ text: preview.slice(cursor), annotation: null })

  return (
    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground section-preview">
      {segments.map((seg, i) =>
        seg.annotation ? (
          <mark
            key={i}
            data-annotation-id={seg.annotation.id}
            className={cn("rounded-sm", COLOR_CLASSES[seg.annotation.color] ?? COLOR_CLASSES.yellow)}
            title={seg.annotation.note_text ?? undefined}
          >
            {seg.text}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </p>
  )
}
