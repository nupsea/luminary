import { X } from "lucide-react"

export interface ReadingPosition {
  document_id: string
  last_section_id: string | null
  last_section_heading: string | null
  last_pdf_page: number | null
  last_epub_chapter_index: number | null
}

interface ResumeBannerProps {
  position: ReadingPosition
  onResume: () => void
  onDismiss: () => void
}

export function ResumeBanner({ position, onResume, onDismiss }: ResumeBannerProps) {
  const label = position.last_section_heading ?? "your last position"
  const pageInfo =
    position.last_pdf_page != null
      ? ` (page ${position.last_pdf_page})`
      : position.last_epub_chapter_index != null
        ? ` (chapter ${position.last_epub_chapter_index + 1})`
        : ""

  return (
    <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-4 py-2 text-xs">
      <span className="flex-1 text-muted-foreground">
        Resume at <span className="font-medium text-foreground">{label}</span>{pageInfo}?
      </span>
      <button
        onClick={onResume}
        className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
      >
        Resume
      </button>
      <button
        onClick={onDismiss}
        className="text-muted-foreground hover:text-foreground"
        aria-label="Dismiss"
      >
        <X size={12} />
      </button>
    </div>
  )
}
