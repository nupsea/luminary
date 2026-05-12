// HealthReportPanel (S160) -- orphaned / mastered / stale /
// uncovered / hotspot metrics for a document's flashcard deck.
// Five-pill summary plus two batch actions: archive mastered cards
// and queue generation for uncovered sections.

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, Check, ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { apiGet, apiPost } from "@/lib/apiClient"

import type { DeckHealthReport } from "./types"

const fetchDeckHealth = (documentId: string): Promise<DeckHealthReport> =>
  apiGet<DeckHealthReport>(`/flashcards/health/${documentId}`)

const archiveMastered = (documentId: string): Promise<{ archived: number }> =>
  apiPost<{ archived: number }>(
    `/flashcards/health/${documentId}/archive-mastered`,
  )

const fillUncovered = (
  documentId: string,
  sectionIds: string[],
): Promise<{ queued: number }> =>
  apiPost<{ queued: number }>(
    `/flashcards/health/${documentId}/fill-uncovered`,
    { section_ids: sectionIds },
  )

interface HealthReportPanelProps {
  documentId: string
}

export function HealthReportPanel({ documentId }: HealthReportPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const qc = useQueryClient()

  const { data: report, isLoading, isError, refetch } = useQuery<DeckHealthReport, Error>({
    queryKey: ["health", documentId],
    queryFn: () => fetchDeckHealth(documentId),
    staleTime: 300_000,
    enabled: isOpen,
  })

  const archiveMutation = useMutation({
    mutationFn: () => archiveMastered(documentId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["health", documentId] })
      qc.invalidateQueries({ queryKey: ["flashcards-search"] })
      toast.success(`Archived ${data.archived} mastered cards`)
    },
    onError: () => {
      toast.error("Failed to archive mastered cards")
    },
  })

  const fillMutation = useMutation({
    mutationFn: () => fillUncovered(documentId, report?.uncovered_section_ids ?? []),
    onSuccess: (data) => {
      toast.success(
        `Generating cards for ${data.queued} uncovered sections in background`,
      )
    },
    onError: () => {
      toast.error("Failed to queue uncovered section fill")
    },
  })

  const totalCards =
    (report?.orphaned ?? 0) + (report?.mastered ?? 0) + (report?.stale ?? 0)

  return (
    <section className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <button
        className="flex items-center justify-between text-left"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="text-base font-semibold text-foreground">Health Report</span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-4 pt-2">
          {isLoading && (
            <div className="flex flex-col gap-2" aria-label="Loading health report">
              {[60, 80, 50, 70, 40].map((w, i) => (
                <div
                  key={i}
                  className="h-8 animate-pulse rounded bg-muted"
                  style={{ width: `${w}%` }}
                />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle size={16} />
              <span>Could not load health report</span>
              <button
                onClick={() => refetch()}
                className="ml-auto rounded border border-red-400 px-2 py-0.5 text-xs hover:bg-red-100 dark:hover:bg-red-900"
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading &&
            !isError &&
            report &&
            totalCards === 0 &&
            report.uncovered_sections === 0 &&
            report.hotspot_sections.length === 0 && (
              <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
                <Check size={16} />
                <span>Deck is healthy -- no issues found</span>
              </div>
            )}

          {!isLoading && !isError && report && (
            <>
              {/* 5 metric pills */}
              <div className="flex flex-wrap gap-2">
                {/* Orphaned */}
                <div
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                    report.orphaned > 0
                      ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                      : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                  }`}
                >
                  <span className="font-bold">{report.orphaned}</span>
                  <span>orphaned</span>
                </div>

                {/* Mastered */}
                <div className="flex items-center gap-1.5 rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                  <span className="font-bold">{report.mastered}</span>
                  <span>mastered</span>
                </div>

                {/* Stale */}
                <div
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                    report.stale > 0
                      ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                      : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                  }`}
                >
                  <span className="font-bold">{report.stale}</span>
                  <span>stale</span>
                </div>

                {/* Uncovered sections */}
                <div
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                    report.uncovered_sections > 0
                      ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                      : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                  }`}
                >
                  <span className="font-bold">{report.uncovered_sections}</span>
                  <span>uncovered</span>
                </div>

                {/* Hotspot */}
                <div className="flex items-center gap-1.5 rounded-full bg-purple-100 px-3 py-1 text-xs font-medium text-purple-800 dark:bg-purple-900 dark:text-purple-200">
                  <span className="font-bold">
                    {report.hotspot_sections.length > 0
                      ? report.hotspot_sections[0].section_heading
                      : "--"}
                  </span>
                  <span>hotspot</span>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex flex-wrap gap-2">
                {report.mastered > 0 && (
                  <button
                    onClick={() => archiveMutation.mutate()}
                    disabled={archiveMutation.isPending}
                    className="flex items-center gap-2 rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {archiveMutation.isPending && (
                      <Loader2 size={14} className="animate-spin" />
                    )}
                    Archive {report.mastered} mastered
                  </button>
                )}

                {report.uncovered_sections > 0 && (
                  <button
                    onClick={() => fillMutation.mutate()}
                    disabled={fillMutation.isPending}
                    className="flex items-center gap-2 rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                  >
                    {fillMutation.isPending && (
                      <Loader2 size={14} className="animate-spin" />
                    )}
                    Generate for {report.uncovered_sections} uncovered sections
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
