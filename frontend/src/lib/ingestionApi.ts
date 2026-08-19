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

export async function submitFile(
  file: File,
  contentType: ContentTypeValue,
): Promise<string> {
  const form = new FormData()
  form.append("file", file)
  form.append("content_type", contentType)
  try {
    const data = await apiPost<{ document_id: string }>(
      "/documents/ingest",
      form,
    )
    return data.document_id
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
