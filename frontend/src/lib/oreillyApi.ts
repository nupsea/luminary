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

// Mirrors is_oreilly_url in oreilly_service.py: match the host, never a substring,
// so an article URL that merely mentions O'Reilly still ingests as an article.
export function isOreillyUrl(url: string): boolean {
  const raw = url?.trim() ?? ""
  if (!raw) return false
  if (raw.toLowerCase().startsWith("urn:orm:book:")) return true
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    return false
  }
  const host = parsed.hostname.toLowerCase()
  if (host === "learning.oreilly.com") return true
  return (host === "oreilly.com" || host === "www.oreilly.com") && parsed.pathname.startsWith("/library/view/")
}

export function parseOreillyChapter(url: string): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    const segments = parsed.pathname.split("/").filter(Boolean)
    if (segments.length >= 2) {
      const last = segments[segments.length - 1]
      if (last.endsWith(".html") || last.endsWith(".xhtml")) {
        return last
      }
    }
  } catch {
    const match = url.match(/\/([^/?#]+\.(?:html|xhtml))(?:[?#]|$)/i)
    if (match) return match[1]
  }
  return null
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
