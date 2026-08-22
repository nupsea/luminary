import { createContext, useContext } from "react"

export type IngestionJobStatus = "processing" | "complete" | "error"

export interface IngestionJob {
  docId: string
  filename: string
  stage: string
  progressPct: number
  status: IngestionJobStatus
  errorMessage: string | null
  /** Consecutive status polls that failed for a reason other than deletion.
   *  A job whose status cannot be read forever is not a job in progress. */
  missedPolls: number
  startedAt: number
}

export interface IngestionTrackerContextValue {
  jobs: Record<string, IngestionJob>
  track: (docId: string, filename: string) => void
  getJob: (docId: string) => IngestionJob | undefined
}

export const IngestionTrackerContext = createContext<IngestionTrackerContextValue | null>(null)

export function useIngestionTracker(): IngestionTrackerContextValue {
  const ctx = useContext(IngestionTrackerContext)
  if (!ctx) throw new Error("useIngestionTracker must be used within IngestionTrackerProvider")
  return ctx
}

export function useIngestionJob(docId: string | null | undefined): IngestionJob | undefined {
  const { jobs } = useIngestionTracker()
  return docId ? jobs[docId] : undefined
}

/** What to do with a tracked job whose status poll failed.
 *
 *  Pure so it can be tested without mounting the provider or faking timers.
 *
 *  The bug it exists for: every rejected poll used to be skipped outright, so a
 *  document deleted mid-ingestion 404ed forever and its job stayed
 *  "processing" -- the progress pill sat at whatever stage it had reached, with
 *  nothing able to clear it.
 */
export type PollFailureOutcome =
  | { action: "drop" }
  | { action: "retry"; missedPolls: number }
  | { action: "give-up" }

export function classifyPollFailure(
  httpStatus: number | null,
  missedPolls: number,
  maxMissedPolls: number,
): PollFailureOutcome {
  // Gone means gone -- the user deleted it, so stop tracking rather than
  // reporting a failure for something they removed on purpose.
  if (httpStatus === 404) return { action: "drop" }
  const missed = missedPolls + 1
  return missed >= maxMissedPolls ? { action: "give-up" } : { action: "retry", missedPolls: missed }
}
