import { apiGet } from "@/lib/apiClient"
import type { components } from "@/types/api"

export type DueCount = components["schemas"]["DueCountResponse"]

// JS getTimezoneOffset(): the backend counts today's new cards from the user's midnight.
export const tzOffsetMinutes = (): number => new Date().getTimezoneOffset()

export const fetchDueCount = (): Promise<DueCount> =>
  apiGet<DueCount>("/study/due-count", { tz_offset_minutes: tzOffsetMinutes() })

/** Today's work: due reviews plus the unseen cards the daily budget lets in (I-83). */
export const cardsToday = (count: DueCount | undefined): number =>
  (count?.due_today ?? 0) + (count?.new_today ?? 0)
