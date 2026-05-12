import { ApiError, apiGet, apiPost } from "@/lib/apiClient"

export type ContentTypeValue =
  | "book"
  | "conversation"
  | "notes"
  | "audio"
  | "video"
  | "epub"
  | "tech_book"
  | "tech_article"

export interface IngestionStatus {
  stage: string
  progress_pct: number
  done: boolean
  error_message: string | null
}

export interface KindleIngestResult {
  document_ids: string[]
  book_count: number
}

function detailFromError(err: unknown, fallback: string): Error {
  if (err instanceof ApiError) {
    try {
      const parsed = JSON.parse(err.body) as { detail?: string }
      if (parsed.detail) return new Error(parsed.detail)
    } catch {
      // body wasn't JSON
    }
    return new Error(fallback)
  }
  return err instanceof Error ? err : new Error(fallback)
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

export async function submitUrl(url: string): Promise<string> {
  try {
    const data = await apiPost<{ document_id: string }>("/documents/ingest-url", {
      url,
    })
    return data.document_id
  } catch (err) {
    throw detailFromError(err, "Ingestion failed")
  }
}

export const fetchIngestionStatus = (docId: string): Promise<IngestionStatus> =>
  apiGet<IngestionStatus>(`/documents/${docId}/status`)
