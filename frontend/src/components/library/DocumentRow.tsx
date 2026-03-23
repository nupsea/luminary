import { Badge } from "@/components/ui/badge"
import type { DocumentListItem } from "./types"
import {
  CONTENT_TYPE_ICONS,
  Youtube,
  STATUS_LABELS,
  STATUS_VARIANTS,
  formatWordCount,
  isYouTubeDoc,
  relativeDate,
} from "./utils"

interface DocumentRowProps {
  doc: DocumentListItem
  onClick: (id: string) => void
}

export function DocumentRow({ doc, onClick }: DocumentRowProps) {
  const Icon = isYouTubeDoc(doc) ? Youtube : CONTENT_TYPE_ICONS[doc.content_type]

  return (
    <div
      className="flex cursor-pointer select-none items-center gap-4 rounded-md border border-border bg-background px-4 py-3 transition-colors hover:bg-accent/50"
      onClick={() => onClick(doc.id)}
    >
      <Icon size={16} className="shrink-0 text-muted-foreground" />
      <span className="flex-1 truncate text-sm font-medium text-foreground">{doc.title}</span>
      <span className="hidden text-xs capitalize text-muted-foreground sm:block">{doc.content_type}</span>
      <span className="hidden text-xs text-muted-foreground md:block">{formatWordCount(doc.word_count)}</span>
      <span className="hidden text-xs text-muted-foreground lg:block">{relativeDate(doc.created_at)}</span>
      {doc.reading_progress_pct > 0 && (
        <span className="hidden text-xs text-muted-foreground xl:block">
          {Math.round(doc.reading_progress_pct * 100)}% read
        </span>
      )}
      {(doc.enrichment_status === "pending" || doc.enrichment_status === "running") && (
        <span className="hidden text-xs text-blue-600 sm:block">Enriching...</span>
      )}
      {doc.enrichment_status === "done" && (
        <span className="hidden text-xs text-green-700 sm:block">Images ready</span>
      )}
      {doc.enrichment_status === "failed" && (
        <span className="hidden text-xs text-orange-600 sm:block">Enrichment failed</span>
      )}
      <Badge variant={STATUS_VARIANTS[doc.learning_status]}>
        {STATUS_LABELS[doc.learning_status]}
      </Badge>
    </div>
  )
}
