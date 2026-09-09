// Polling hook that resolves async teach-back evaluations submitted during
// a session. Returns the latest results array plus aggregate stats; SessionComplete
// and the reader's RecallRunner are the consumers.
//
// The stats count CARDS, not submissions -- see latestAttempts.ts for why, and
// for what counting submissions did to the summary of a re-answered card.

import { useQuery } from "@tanstack/react-query"

import {
  type PendingTeachback,
  type TeachbackResultItem,
  fetchTeachbackResults,
} from "@/lib/studyApi"

import { tallyRun } from "./latestAttempts"

export interface TeachbackStats {
  allDone: boolean
  /** Distinct cards answered, however many explanations each took. */
  answeredCount: number
  /** Distinct cards whose standing attempt came back with a score. */
  completedCount: number
  /** Mean of the standing scores -- null while any is unscored, never 0. */
  avgScore: number | null
  passCount: number
  stillScoring: number
}

export function useTeachbackPolling(pending: PendingTeachback[]): {
  results: TeachbackResultItem[] | undefined
  stats: TeachbackStats
} {
  const realIds = pending
    .map((t) => t.id)
    .filter((id) => !id.startsWith("temp-") && !id.startsWith("error-"))
  const hasUnresolved = pending.some(
    (t) => t.id.startsWith("temp-") || t.id.startsWith("error-"),
  )
  const { data: results } = useQuery({
    queryKey: ["teachback-results", ...realIds],
    queryFn: () => fetchTeachbackResults(realIds),
    refetchInterval: (query) => {
      if (hasUnresolved) return 2000
      const items = query.state.data
      if (!items) return 2000
      return items.every((r) => r.status !== "pending") ? false : 2000
    },
    enabled: realIds.length > 0 || hasUnresolved,
    refetchOnMount: "always",
  })

  const tally = tallyRun(pending, results)
  return {
    results,
    stats: {
      // A run with nothing submitted is not "done" -- it has not started.
      allDone: pending.length > 0 && tally.stillScoring === 0,
      answeredCount: tally.answered,
      completedCount: tally.scored,
      avgScore: tally.avgScore,
      passCount: tally.passed,
      stillScoring: tally.stillScoring,
    },
  }
}
