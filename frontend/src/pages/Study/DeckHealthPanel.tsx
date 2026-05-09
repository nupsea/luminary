// DeckHealthPanel (S153) -- Bloom's taxonomy coverage audit.
//
// Collapsible panel showing the document's flashcards bucketed by
// Bloom level (1..6), a coverage score badge, a per-section gap
// list, and a "Fill Bloom Gaps" mutation. Owns its own
// fetch/mutation; only the documentId comes in as a prop.

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { toast } from "sonner"

import { API_BASE } from "@/lib/config"

import type { CoverageReport } from "./types"
import { bloomBarFill, coverageBadgeClass } from "./utils"

async function fetchAudit(documentId: string): Promise<CoverageReport> {
  const res = await fetch(`${API_BASE}/flashcards/audit/${documentId}`)
  if (!res.ok) throw new Error("Failed to load deck health")
  return res.json() as Promise<CoverageReport>
}

async function fillAuditGaps(documentId: string): Promise<{ created: number }> {
  const res = await fetch(`${API_BASE}/flashcards/audit/${documentId}/fill`, {
    method: "POST",
  })
  if (!res.ok) throw new Error("Failed to fill Bloom gaps")
  return res.json() as Promise<{ created: number }>
}

interface DeckHealthPanelProps {
  documentId: string
}

export function DeckHealthPanel({ documentId }: DeckHealthPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [gapsOpen, setGapsOpen] = useState(false)
  const qc = useQueryClient()

  const { data: report, isLoading, isError, refetch } = useQuery<CoverageReport, Error>({
    queryKey: ["audit", documentId],
    queryFn: () => fetchAudit(documentId),
    staleTime: 30_000,
    enabled: isOpen,
  })

  const fillMutation = useMutation({
    mutationFn: () => fillAuditGaps(documentId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["audit", documentId] })
      toast.success(`Created ${data.created} new Bloom gap cards`)
    },
    onError: () => {
      toast.error("Failed to fill Bloom gaps")
    },
  })

  const chartData = report
    ? [1, 2, 3, 4, 5, 6].map((level) => ({
        name: `L${level}`,
        count: report.by_bloom_level[String(level)] ?? 0,
        fill: bloomBarFill(level),
      }))
    : []

  return (
    <section className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <button
        className="flex items-center justify-between text-left"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="text-base font-semibold text-foreground">Deck Health</span>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="flex flex-col gap-4 pt-2">
          {isLoading && (
            <div className="flex flex-col gap-2" aria-label="Loading deck health">
              {[40, 70, 55, 30, 20, 15].map((w, i) => (
                <div
                  key={i}
                  className="h-5 animate-pulse rounded bg-muted"
                  style={{ width: `${w}%` }}
                />
              ))}
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle size={16} />
              <span>Could not load deck health</span>
              <button
                onClick={() => refetch()}
                className="ml-auto rounded border border-red-400 px-2 py-0.5 text-xs hover:bg-red-100 dark:hover:bg-red-900"
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading && !isError && report && report.total_cards === 0 && (
            <p className="text-sm text-muted-foreground">
              No flashcards yet -- generate some to see Bloom distribution.
            </p>
          )}

          {!isLoading && !isError && report && report.total_cards > 0 && (
            <>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">Coverage score</span>
                <span
                  className={`rounded px-2 py-0.5 text-xs font-semibold ${coverageBadgeClass(report.coverage_score)}`}
                >
                  {Math.round(report.coverage_score * 100)}%
                </span>
              </div>

              {/* Bloom level bar chart */}
              <div className="h-40 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                    <Tooltip formatter={(value) => [value ?? 0, "Cards"]} />
                    <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                      {chartData.map((entry, index) => (
                        <Cell key={`bar-${index}`} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Fill Gaps button */}
              {report.gaps.length > 0 && (
                <button
                  onClick={() => fillMutation.mutate()}
                  disabled={fillMutation.isPending}
                  className="flex items-center gap-2 self-start rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                >
                  {fillMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                  Fill Bloom Gaps
                </button>
              )}

              {/* Per-section gap list */}
              {report.gaps.length > 0 && (
                <div className="flex flex-col gap-1">
                  <button
                    className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => setGapsOpen((v) => !v)}
                  >
                    {gapsOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    {report.gaps.length} section{report.gaps.length > 1 ? "s" : ""} missing L3+ cards
                  </button>
                  {gapsOpen && (
                    <ul className="ml-4 flex flex-col gap-1">
                      {report.gaps.map((gap) => (
                        <li key={gap.section_id} className="text-xs text-muted-foreground">
                          <span className="font-medium text-foreground">{gap.section_heading}</span>
                          {" — missing L"}
                          {gap.missing_bloom_levels.join(", L")}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {report.gaps.length === 0 && (
                <p className="text-xs text-green-700 dark:text-green-400">
                  All sections have L3+ cards -- good coverage!
                </p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
