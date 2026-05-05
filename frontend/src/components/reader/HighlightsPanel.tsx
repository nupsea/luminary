import { Trash2 } from "lucide-react"
import { useState } from "react"

import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"

import type { AnnotationItem } from "./types"

const COLOR_CLASSES: Record<string, string> = {
  yellow: "bg-yellow-200 dark:bg-yellow-900/50",
  green: "bg-green-200 dark:bg-green-900/50",
  blue: "bg-blue-200 dark:bg-blue-900/50",
  pink: "bg-pink-200 dark:bg-pink-900/50",
}

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
        // eslint-disable-next-line react/no-danger
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

interface HighlightsPanelProps {
  annotations: AnnotationItem[]
  loading: boolean
  error: boolean
  onDelete: (id: string) => void
}

export function HighlightsPanel({ annotations, loading, error, onDelete }: HighlightsPanelProps) {
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleConfirmDelete(id: string) {
    setDeleting(true)
    try {
      await fetch(`${API_BASE}/annotations/${id}`, { method: "DELETE" })
      onDelete(id)
      setConfirmDelete(null)
    } catch {
      // keep confirm open so user can retry
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-2 px-6 py-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-md bg-muted" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-6 py-3">
        <p className="text-xs text-destructive">Could not load highlights.</p>
      </div>
    )
  }

  if (annotations.length === 0) {
    return (
      <div className="px-6 py-3">
        <p className="text-xs text-muted-foreground">
          No highlights yet. Select text and click Highlight.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 px-6 py-3">
      {annotations.map((ann) => (
        <div key={ann.id} className="rounded-md border border-border p-2">
          {confirmDelete === ann.id ? (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-foreground">Delete this highlight?</p>
              <div className="flex gap-2">
                <button
                  onClick={() => void handleConfirmDelete(ann.id)}
                  disabled={deleting}
                  className="rounded bg-destructive px-2 py-0.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                >
                  {deleting ? "Deleting..." : "Yes"}
                </button>
                <button
                  onClick={() => setConfirmDelete(null)}
                  disabled={deleting}
                  className="rounded border border-border px-2 py-0.5 text-xs hover:bg-accent disabled:opacity-50"
                >
                  No
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  "mt-0.5 h-2 w-2 shrink-0 rounded-full",
                  COLOR_CLASSES[ann.color] ?? COLOR_CLASSES.yellow,
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs text-foreground" title={ann.selected_text}>
                  {ann.selected_text.length > 60
                    ? `${ann.selected_text.slice(0, 60)}...`
                    : ann.selected_text}
                </p>
                {ann.note_text && (
                  <p className="mt-0.5 text-xs text-muted-foreground">{ann.note_text}</p>
                )}
              </div>
              <button
                onClick={() => setConfirmDelete(ann.id)}
                title="Delete highlight"
                className="shrink-0 text-muted-foreground hover:text-destructive"
              >
                <Trash2 size={12} />
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
