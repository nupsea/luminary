// Continue-reading affordance at the top of Library. The Hub owns the single
// "Today" recall CTA (due cards / start review); Library is the reception
// surface, so here we only nudge picking the last doc back up. Due-card
// visibility on Library lives in the stats bar, not a second competing hero.
// Renders nothing when there's nothing in progress.

import { BookOpen } from "lucide-react"

import type { DocumentListItem } from "@/components/library/types"

interface TodayHeroProps {
  recentItem: DocumentListItem | undefined
  onContinue: (id: string) => void
}

export function TodayHero({ recentItem, onContinue }: TodayHeroProps) {
  if (!recentItem) return null
  return (
    <div
      className="flex cursor-pointer select-none items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 transition-colors hover:bg-primary/10"
      onClick={() => onContinue(recentItem.id)}
    >
      <BookOpen size={15} className="shrink-0 text-primary" />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="lum-eyebrow text-primary">Continue reading</span>
        <span className="truncate text-sm font-medium text-foreground">{recentItem.title}</span>
      </div>
      {recentItem.reading_progress_pct > 0 && (
        <span className="shrink-0 text-xs text-muted-foreground">
          {Math.round(recentItem.reading_progress_pct * 100)}% read
        </span>
      )}
    </div>
  )
}
