import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { DocumentListItem } from "./types"
import {
  CONTENT_TYPE_ICONS,
  STATUS_LABELS,
  STATUS_VARIANTS,
  formatWordCount,
  relativeDate,
} from "./utils"

interface DocumentCardProps {
  doc: DocumentListItem
  onClick: (id: string) => void
}

export function DocumentCard({ doc, onClick }: DocumentCardProps) {
  const Icon = CONTENT_TYPE_ICONS[doc.content_type]

  return (
    <Card
      className="cursor-pointer select-none"
      onClick={() => onClick(doc.id)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={16} className="shrink-0 text-muted-foreground" />
          <h3 className="truncate text-sm font-semibold text-foreground">{doc.title}</h3>
        </div>
        <Badge variant={STATUS_VARIANTS[doc.learning_status]}>
          {STATUS_LABELS[doc.learning_status]}
        </Badge>
      </div>

      <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="capitalize">{doc.content_type}</span>
        <span>·</span>
        <span>{formatWordCount(doc.word_count)}</span>
        <span>·</span>
        <span>{relativeDate(doc.created_at)}</span>
      </div>

      {doc.summary_one_sentence && (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
          {doc.summary_one_sentence}
        </p>
      )}

      {doc.flashcard_count > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          {doc.flashcard_count} flashcard{doc.flashcard_count !== 1 ? "s" : ""}
        </p>
      )}
    </Card>
  )
}
