import { createContext, useContext } from "react"

export type IngestionJobStatus = "processing" | "complete" | "error"

export interface IngestionJob {
  docId: string
  filename: string
  stage: string
  progressPct: number
  status: IngestionJobStatus
  errorMessage: string | null
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
