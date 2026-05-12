import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"

import { apiPost } from "@/lib/apiClient"

async function postReadingProgress(documentId: string, sectionId: string): Promise<void> {
  try {
    await apiPost("/reading/progress", {
      document_id: documentId,
      section_id: sectionId,
    })
  } catch {
    // Best-effort: network errors must never interrupt reading
  }
}

// Posts a progress event after a section is visible for 3 seconds (dwell-time).
// On unmount, invalidates the library query so document cards re-render
// with the updated progress bar.
export function useReadingProgress(documentId: string, sectionCount: number) {
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const progressPosted = useRef(false)
  const qc = useQueryClient()

  useEffect(() => {
    if (sectionCount === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const sectionId = (entry.target as HTMLElement).dataset["sectionId"]
          if (!sectionId) continue

          if (entry.isIntersecting) {
            if (!timers.current.has(sectionId)) {
              const t = setTimeout(() => {
                timers.current.delete(sectionId)
                progressPosted.current = true
                void postReadingProgress(documentId, sectionId)
              }, 3000)
              timers.current.set(sectionId, t)
            }
          } else {
            const t = timers.current.get(sectionId)
            if (t !== undefined) {
              clearTimeout(t)
              timers.current.delete(sectionId)
            }
          }
        }
      },
      { threshold: 0.5 },
    )

    const elements = document.querySelectorAll("[data-section-id]")
    for (const el of elements) observer.observe(el)

    return () => {
      observer.disconnect()
      for (const t of timers.current.values()) clearTimeout(t)
      timers.current.clear()
      if (progressPosted.current) {
        void qc.invalidateQueries({ queryKey: ["documents"] })
        progressPosted.current = false
      }
    }
  }, [documentId, sectionCount, qc])
}
