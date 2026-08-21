import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"

import { apiPost } from "@/lib/apiClient"

import { DWELL_MS, isBeingRead, sampleFromEntry, THRESHOLDS } from "./readingDwell"

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

// Only this pane's sections count. The contents list renders `data-section-id`
// on every row, so an unscoped observer recorded scrolling a table of contents
// as reading the document.
const READING_SURFACE = "[data-reading-surface]"

/**
 * Record a section as read once it has genuinely held the screen.
 *
 * Sections are observed as they appear, not once at mount. `sectionCount`
 * arrives with `GET /documents/{id}` while the elements themselves arrive with
 * `GET /sections/{id}/content`, so a single `querySelectorAll` in the effect
 * body raced the second query and usually found nothing -- and since the deps
 * never changed again, that visit recorded no progress at all. Measured on one
 * library: three documents that had been opened carried a `content_activity`
 * row and zero `reading_progress` rows, which is what kept them out of the
 * hub's "continue reading" lane (it requires read_count > 0).
 *
 * The same gap swallowed sections appended later, because the reader extends
 * its render window as you scroll and those elements never existed when the
 * observer was attached.
 */
export function useReadingProgress(
  documentId: string,
  sectionCount: number,
  rootRef?: React.RefObject<HTMLElement | null>,
) {
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const progressPosted = useRef(false)
  const qc = useQueryClient()

  useEffect(() => {
    if (sectionCount === 0) return
    // Bounded to the reader when it has painted, so the mutation callback is
    // not woken by unrelated DOM churn elsewhere in the app.
    const root: ParentNode = rootRef?.current ?? document.body

    const seen = new WeakSet<Element>()
    const timerMap = timers.current

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const sectionId = (entry.target as HTMLElement).dataset["sectionId"]
          if (!sectionId) continue

          if (isBeingRead(sampleFromEntry(entry))) {
            if (!timerMap.has(sectionId)) {
              const t = setTimeout(() => {
                timerMap.delete(sectionId)
                progressPosted.current = true
                void postReadingProgress(documentId, sectionId)
              }, DWELL_MS)
              timerMap.set(sectionId, t)
            }
          } else {
            const t = timerMap.get(sectionId)
            if (t !== undefined) {
              clearTimeout(t)
              timerMap.delete(sectionId)
            }
          }
        }
      },
      { threshold: THRESHOLDS },
    )

    // A hidden pane's sections are observed too, which costs nothing: a
    // `display: none` subtree never reports itself as intersecting. That is
    // what lets the surface stay observed across a tab switch.
    function observeWithin(node: ParentNode) {
      for (const surface of node.querySelectorAll(READING_SURFACE)) {
        for (const el of surface.querySelectorAll("[data-section-id]")) {
          if (!seen.has(el)) {
            seen.add(el)
            observer.observe(el)
          }
        }
      }
    }

    observeWithin(root)

    // Picks up the sections the content query paints after mount, and every
    // batch the reader appends as its window grows.
    const mutations = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (!(node instanceof Element)) continue
          const surface = node.closest(READING_SURFACE)
          if (surface) {
            if (node.matches("[data-section-id]") && !seen.has(node)) {
              seen.add(node)
              observer.observe(node)
            }
            for (const el of node.querySelectorAll("[data-section-id]")) {
              if (!seen.has(el)) {
                seen.add(el)
                observer.observe(el)
              }
            }
          }
          observeWithin(node)
        }
      }
    })
    mutations.observe(root as Node, { childList: true, subtree: true })

    return () => {
      mutations.disconnect()
      observer.disconnect()
      for (const t of timerMap.values()) clearTimeout(t)
      timerMap.clear()
      if (progressPosted.current) {
        // The hub reads reading_progress for its "continue reading" lane, so it
        // is as stale as the library card if only `documents` is invalidated.
        void qc.invalidateQueries({ queryKey: ["documents"] })
        void qc.invalidateQueries({ queryKey: ["home-overview"] })
        progressPosted.current = false
      }
    }
  }, [documentId, sectionCount, qc, rootRef])
}
