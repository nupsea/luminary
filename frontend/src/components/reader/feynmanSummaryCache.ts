/**
 * Summary prefetch cache for FeynmanDialog.
 *
 * Lets the Practice button warm the section summary on hover/focus so the
 * dialog opens with content already in hand instead of a 200-500ms skeleton.
 * Lives in its own module so FeynmanDialog.tsx exports only its component
 * (required by the react-refresh / fast-refresh rule).
 */

import { apiGet } from "@/lib/apiClient"

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
    const data = await apiGet<{
      summaries: Record<string, { id: string; content: string }>
    }>(`/summarize/${documentId}/cached`)
    if (data.summaries["executive"]) return data.summaries["executive"].content
  } catch {
    // fall through
  }
  try {
    const doc = await apiGet<{
      sections: Array<{ id: string; preview: string }>
    }>(`/documents/${documentId}`)
    const section = doc.sections.find((s) => s.id === sectionId)
    if (section?.preview) return section.preview
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
