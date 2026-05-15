// Compact single-row stats pills. Replaced the large LibraryOverview
// SSE panel; each pill fires a luminary:navigate event on click.

import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import { buildStatPillNavigateDetail, computeAvgMastery, STAT_PILL_LABELS } from "@/lib/learningUtils"

import { fetchDueCount, fetchNotesCount, fetchRecentSessions } from "./api"

interface LibraryStatsBarProps {
  totalDocuments: number
  isDocumentsLoading: boolean
}

export function LibraryStatsBar({ totalDocuments, isDocumentsLoading }: LibraryStatsBarProps) {
  const { data: dueData, isLoading: isDueLoading } = useQuery({
    queryKey: ["stats-due-count"],
    queryFn: fetchDueCount,
    staleTime: 60_000,
  })

  const { data: sessionsData, isLoading: isSessionsLoading } = useQuery({
    queryKey: ["stats-sessions"],
    queryFn: fetchRecentSessions,
    staleTime: 60_000,
  })

  const { data: notesCount, isLoading: isNotesLoading } = useQuery({
    queryKey: ["stats-notes-count"],
    queryFn: fetchNotesCount,
    staleTime: 60_000,
  })

  const avgMastery =
    sessionsData && !isSessionsLoading
      ? computeAvgMastery(sessionsData.items.map((s) => s.accuracy_pct))
      : null

  function handlePillClick(pill: "study" | "notes" | "progress") {
    window.dispatchEvent(
      new CustomEvent("luminary:navigate", { detail: buildStatPillNavigateDetail(pill) })
    )
  }

  const pillBase =
    "flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground cursor-pointer select-none"

  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Library stats">
      {/* Books count -- no navigation, just informational */}
      <span className={pillBase} style={{ cursor: "default" }}>
        {isDocumentsLoading ? (
          <Skeleton className="h-3 w-8 inline-block" />
        ) : (
          <strong>{totalDocuments}</strong>
        )}
        <span className="text-muted-foreground">{STAT_PILL_LABELS.books}</span>
      </span>

      {/* Notes count -- navigates to Notes tab */}
      <button className={pillBase} onClick={() => handlePillClick("notes")}>
        {isNotesLoading ? (
          <Skeleton className="h-3 w-8 inline-block" />
        ) : (
          <strong>{notesCount ?? 0}</strong>
        )}
        <span className="text-muted-foreground">{STAT_PILL_LABELS.notes}</span>
      </button>

      {/* Avg mastery -- navigates to Progress tab */}
      <button className={pillBase} onClick={() => handlePillClick("progress")}>
        {isSessionsLoading ? (
          <Skeleton className="h-3 w-8 inline-block" />
        ) : avgMastery !== null ? (
          <strong>{avgMastery}%</strong>
        ) : (
          <strong className="text-muted-foreground">--</strong>
        )}
        <span className="text-muted-foreground">{STAT_PILL_LABELS.mastery}</span>
      </button>

      {/* Cards due -- navigates to Study tab */}
      <button className={pillBase} onClick={() => handlePillClick("study")}>
        {isDueLoading ? (
          <Skeleton className="h-3 w-8 inline-block" />
        ) : (
          <strong>{dueData?.due_today ?? 0}</strong>
        )}
        <span className="text-muted-foreground">{STAT_PILL_LABELS.due}</span>
      </button>
    </div>
  )
}
