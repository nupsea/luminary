// Single highest-leverage learning action at the top of Library.
// Priority: due flashcards (recall) > continue reading (reception).
// Renders nothing when neither applies.

import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { BookOpen, Zap } from "lucide-react"

import type { DocumentListItem } from "@/components/library/types"

import { fetchDueCount } from "./api"

interface TodayHeroProps {
  recentItem: DocumentListItem | undefined
  onContinue: (id: string) => void
}

export function TodayHero({ recentItem, onContinue }: TodayHeroProps) {
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ["stats-due-count"],
    queryFn: fetchDueCount,
    staleTime: 60_000,
  })
  const dueCount = data?.due_today ?? 0

  if (dueCount === 0 && !recentItem) return null

  if (dueCount > 0) {
    return (
      <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
        <button
          onClick={() => navigate("/study")}
          className="group flex flex-1 cursor-pointer select-none items-center gap-3 rounded-lg bg-primary px-4 py-3 text-left text-primary-foreground transition-all hover:bg-primary/90 hover:shadow-md"
        >
          <Zap size={16} className="shrink-0" />
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="lum-eyebrow text-primary-foreground/70">Today</span>
            <span className="truncate text-sm font-semibold">
              {dueCount} card{dueCount !== 1 ? "s" : ""} due · Start review
            </span>
          </div>
          <span className="hidden shrink-0 text-xs text-primary-foreground/70 sm:inline">→</span>
        </button>
        {recentItem && (
          <button
            onClick={() => onContinue(recentItem.id)}
            className="flex cursor-pointer select-none items-center gap-3 rounded-lg border border-border bg-background px-4 py-3 text-left transition-colors hover:bg-accent sm:w-[42%]"
          >
            <BookOpen size={14} className="shrink-0 text-muted-foreground" />
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="lum-eyebrow">Or continue reading</span>
              <span className="truncate text-sm text-foreground">{recentItem.title}</span>
            </div>
          </button>
        )}
      </div>
    )
  }

  // No cards due -- fall back to the existing continue-reading affordance.
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
