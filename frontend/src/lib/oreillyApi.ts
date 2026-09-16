import { apiGet, apiPost, apiDelete, detailFromError } from "@/lib/apiClient"

export interface OreillyStatus {
  configured: boolean
  valid: boolean
  user?: string | null
  error?: string | null
}

export interface OreillyChapterPreview {
  index: number
  title: string
  minutes_required?: number | null
}

export interface OreillyBookPreview {
  book_id: string
  title?: string | null
  authors?: string[] | null
  description?: string | null
  cover_url?: string | null
  chapter_count: number
  chapters: OreillyChapterPreview[]
}

export interface OreillyIngestResult {
  document_id: string
  status: string
  title: string
}

export function isOreillyUrl(url: string): boolean {
  if (!url) return false
  const lower = url.trim().toLowerCase()
  return (
    lower.includes("learning.oreilly.com") ||
    lower.includes("oreilly.com/library/view") ||
    lower.startsWith("urn:orm:book:")
  )
}

export async function fetchOreillyStatus(): Promise<OreillyStatus> {
  try {
    return await apiGet<OreillyStatus>("/oreilly/status")
  } catch {
    return { configured: false, valid: false, user: null }
  }
}

export async function saveOreillyCookies(
  cookies: string | Record<string, unknown> | unknown[],
): Promise<{ status: string; valid: boolean; user?: string | null }> {
  try {
    return await apiPost<{ status: string; valid: boolean; user?: string | null }>(
      "/oreilly/cookies",
      { cookies },
    )
  } catch (err) {
    throw detailFromError(err, "Failed to validate and save O'Reilly cookies")
  }
}

export async function clearOreillyCookies(): Promise<void> {
  try {
    await apiDelete("/oreilly/cookies")
  } catch (err) {
    throw detailFromError(err, "Failed to remove O'Reilly cookies")
  }
}

export async function previewOreillyBook(url: string): Promise<OreillyBookPreview> {
  try {
    return await apiPost<OreillyBookPreview>("/oreilly/preview", { url })
  } catch (err) {
    throw detailFromError(err, "Failed to preview O'Reilly book")
  }
}

export async function ingestOreillyBook(
  url: string,
  selectedChapters?: number[],
): Promise<OreillyIngestResult> {
  try {
    return await apiPost<OreillyIngestResult>("/oreilly/ingest", {
      url,
      selected_chapters: selectedChapters,
    })
  } catch (err) {
    throw detailFromError(err, "Failed to start O'Reilly book ingestion")
  }
}
