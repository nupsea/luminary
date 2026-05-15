import { useQueryClient } from "@tanstack/react-query"
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { toast } from "sonner"
import { logger } from "@/lib/logger"
import { fetchIngestionStatus } from "@/lib/ingestionApi"
import {
  IngestionTrackerContext,
  type IngestionJob,
  type IngestionTrackerContextValue,
} from "./ingestionTrackerCore"

const POLL_INTERVAL_MS = 2000

export function IngestionTrackerProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [jobs, setJobs] = useState<Record<string, IngestionJob>>({})
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const jobsRef = useRef<Record<string, IngestionJob>>({})

  // Mirror jobs into a ref so the interval callback always sees fresh state
  // without re-binding the timer every time a stage tick re-renders.
  useEffect(() => {
    jobsRef.current = jobs
  }, [jobs])

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  const pollOnce = useCallback(async () => {
    const active = Object.values(jobsRef.current).filter((j) => j.status === "processing")
    if (active.length === 0) {
      stopPolling()
      return
    }
    const results = await Promise.allSettled(
      active.map(async (job) => ({ job, status: await fetchIngestionStatus(job.docId) })),
    )
    setJobs((prev) => {
      const next = { ...prev }
      let mutated = false
      for (const r of results) {
        if (r.status !== "fulfilled") continue
        const { job, status } = r.value
        const current = next[job.docId]
        if (!current || current.status !== "processing") continue

        if (status.stage === "error" || status.error_message) {
          const errMsg = status.error_message ?? "Ingestion failed"
          logger.error("[Ingestion] failed", {
            doc_id: job.docId,
            stage: status.stage,
            error_message: errMsg,
          })
          toast.error(`${job.filename}: ${errMsg}`, { id: job.docId })
          next[job.docId] = { ...current, status: "error", stage: status.stage, errorMessage: errMsg }
          mutated = true
          continue
        }

        const updated: IngestionJob = {
          ...current,
          stage: status.stage,
          progressPct: status.progress_pct,
        }

        if (status.done) {
          updated.status = "complete"
          updated.progressPct = 100
          logger.info("[Ingestion] complete", {
            doc_id: job.docId,
            filename: job.filename,
            elapsed_ms: Date.now() - job.startedAt,
          })
          toast.success(`${job.filename}: ready`, { id: job.docId })
          void queryClient.invalidateQueries({ queryKey: ["documents"] })
          void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
        }

        next[job.docId] = updated
        mutated = true
      }
      return mutated ? next : prev
    })
  }, [queryClient, stopPolling])

  const ensurePolling = useCallback(() => {
    if (intervalRef.current) return
    intervalRef.current = setInterval(() => {
      void pollOnce()
    }, POLL_INTERVAL_MS)
  }, [pollOnce])

  const track = useCallback(
    (docId: string, filename: string) => {
      const newJob: IngestionJob = {
        docId,
        filename,
        stage: "parsing",
        progressPct: 5,
        status: "processing",
        errorMessage: null,
        startedAt: Date.now(),
      }
      setJobs((prev) => {
        if (prev[docId] && prev[docId].status === "processing") return prev
        return { ...prev, [docId]: newJob }
      })
      // Eagerly update the ref so pollOnce (which reads jobsRef) can see
      // the new job immediately, before React commits the state update.
      jobsRef.current = { ...jobsRef.current, [docId]: newJob }
      toast.info(`${filename}: ingestion started`, { id: docId, duration: 3000 })
      ensurePolling()
      // Defer the first poll to the next microtask so the interval created
      // by ensurePolling() isn't killed by a premature stopPolling() call.
      setTimeout(() => void pollOnce(), 0)
    },
    [ensurePolling, pollOnce],
  )

  const getJob = useCallback((docId: string) => jobsRef.current[docId], [])

  useEffect(() => stopPolling, [stopPolling])

  const value = useMemo<IngestionTrackerContextValue>(
    () => ({ jobs, track, getJob }),
    [jobs, track, getJob],
  )

  return <IngestionTrackerContext.Provider value={value}>{children}</IngestionTrackerContext.Provider>
}
