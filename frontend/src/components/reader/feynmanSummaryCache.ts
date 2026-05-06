/**
 * Summary prefetch cache for FeynmanDialog.
 *
 * Lets the Practice button warm the section summary on hover/focus so the
 * dialog opens with content already in hand instead of a 200-500ms skeleton.
 * Lives in its own module so FeynmanDialog.tsx exports only its component
 * (required by the react-refresh / fast-refresh rule).
 */

import { API_BASE } from "@/lib/config"

export const summaryCache = new Map<string, string>()
export const summaryInflight = new Map<string, Promise<string | null>>()

export function summaryCacheKey(documentId: string, sectionId: string): string {
  return `${documentId}::${sectionId}`
}

export async function fetchSummary(
  documentId: string,
  sectionId: string,
): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/summarize/${documentId}/cached`)
    if (res.ok) {
      const data = (await res.json()) as {
        summaries: Record<string, { id: string; content: string }>
      }
      if (data.summaries["executive"]) return data.summaries["executive"].content
    }
  } catch {
    // fall through
  }
  try {
    const res2 = await fetch(`${API_BASE}/documents/${documentId}`)
    if (res2.ok) {
      const doc = (await res2.json()) as {
        sections: Array<{ id: string; preview: string }>
      }
      const section = doc.sections.find((s) => s.id === sectionId)
      if (section?.preview) return section.preview
    }
  } catch {
    // ignore
  }
  return null
}

export function prefetchFeynmanSummary(documentId: string, sectionId: string): void {
  const key = summaryCacheKey(documentId, sectionId)
  if (summaryCache.has(key) || summaryInflight.has(key)) return
  const p = fetchSummary(documentId, sectionId).then((content) => {
    summaryInflight.delete(key)
    if (content !== null) summaryCache.set(key, content)
    return content
  })
  summaryInflight.set(key, p)
}
