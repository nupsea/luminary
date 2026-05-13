// Polling hook that resolves async teach-back evaluations submitted during
// a session. Returns the latest results array plus aggregate stats; SessionComplete
// is the primary consumer.

import { useQuery } from "@tanstack/react-query"

import {
  type PendingTeachback,
  type TeachbackResultItem,
  fetchTeachbackResults,
} from "@/lib/studyApi"

export interface TeachbackStats {
  allDone: boolean
  completedCount: number
  avgScore: number
  passCount: number
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

  const completed = results?.filter((r) => r.status === "complete") ?? []
  const allDone =
    !hasUnresolved &&
    results != null &&
    results.length === realIds.length &&
    results.every((r) => r.status !== "pending")
  const avgScore =
    completed.length > 0
      ? Math.round(completed.reduce((s, r) => s + (r.score ?? 0), 0) / completed.length)
      : 0
  const passCount = completed.filter((r) => (r.score ?? 0) >= 60).length

  return {
    results,
    stats: { allDone, completedCount: completed.length, avgScore, passCount },
  }
}
