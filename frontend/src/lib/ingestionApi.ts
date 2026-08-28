import { renderPage } from "@/lib/pageRender"
import { apiGet, apiPost, detailFromError } from "@/lib/apiClient"

export type ContentTypeValue =
  | "book"
  | "technical"
  | "paper"
  | "conversation"
  | "notes"
  | "audio"
  | "video"
  // Legacy stored values still accepted by the backend; not offered in the
  // upload UI ("technical" resolves to a tech_* variant at ingest).
  | "epub"
  | "tech_book"
  | "tech_article"

export interface IngestionStatus {
  stage: string
  progress_pct: number
  done: boolean
  /** Background indexing is being held back for an in-flight question. */
  paused_for_interaction?: boolean
  error_message: string | null
}

export interface KindleIngestResult {
  document_ids: string[]
  book_count: number
}

/** The type the backend detects for this file, without ingesting it.
 *
 *  Detection needs the document's text, so it cannot happen in the browser.
 *  Returns null when detection fails or is not applicable -- never a guess:
 *  the value is shown to the user as what Luminary decided, and a fabricated
 *  one would be indistinguishable from a real detection.
 */
export async function detectFileType(file: File): Promise<ContentTypeValue | null> {
  const form = new FormData()
  form.append("file", file)
  try {
    const data = await apiPost<{ content_type: ContentTypeValue | null }>(
      "/documents/detect-type",
      form,
    )
    return data.content_type ?? null
  } catch {
    // Detection is an convenience, not a gate: ingestion classifies anyway.
    return null
  }
}

export interface FileIngestResult {
  documentId: string
  /** The library already held this file; nothing is running, so do not track it. */
  duplicate: boolean
}

export async function submitFile(
  file: File,
  contentType: ContentTypeValue | null,
): Promise<FileIngestResult> {
  const form = new FormData()
  form.append("file", file)
  // Omitted, not blank, when the user did not choose: the backend skips
  // classification for any supplied content_type, so sending a guess here
  // silently overrides detection.
  if (contentType) form.append("content_type", contentType)
  try {
    const data = await apiPost<{ document_id: string; status: string }>(
      "/documents/ingest",
      form,
    )
    return { documentId: data.document_id, duplicate: data.status === "duplicate" }
  } catch (err) {
    throw detailFromError(err, "Upload failed")
  }
}

export async function submitKindleFile(file: File): Promise<KindleIngestResult> {
  const form = new FormData()
  form.append("file", file)
  try {
    return await apiPost<KindleIngestResult>("/documents/ingest-kindle", form)
  } catch (err) {
    throw detailFromError(err, "Kindle import failed")
  }
}

export interface UrlIngestResult {
  documentId: string
  warnings: string[]
}

export async function submitUrl(url: string): Promise<UrlIngestResult> {
  try {
    // Rendered here rather than in the backend: the desktop shell owns the
    // webview, and the backend has no browser on any platform. Null on every
    // other install, where the static fetch already handles the page.
    const rendered = await renderPage(url)
    const data = await apiPost<{ document_id: string; warnings?: string[] }>(
      "/documents/ingest-url",
      {
        url,
        // Reported even when null: the backend log is the only place the two
        // reasons for a static import -- no shell, or a shell that failed -- can
        // be told apart.
        render_state: rendered.state,
        ...(rendered.detail ? { render_detail: rendered.detail } : {}),
        ...(rendered.html ? { rendered_html: rendered.html } : {}),
      },
    )
    return { documentId: data.document_id, warnings: data.warnings ?? [] }
  } catch (err) {
    throw detailFromError(err, "Ingestion failed")
  }
}

export const fetchIngestionStatus = (docId: string): Promise<IngestionStatus> =>
  apiGet<IngestionStatus>(`/documents/${docId}/status`)
