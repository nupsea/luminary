import { API_BASE } from "@/lib/config"

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

export async function submitFile(file: File, contentType: ContentTypeValue): Promise<string> {
  const form = new FormData()
  form.append("file", file)
  form.append("content_type", contentType)
  const res = await fetch(`${API_BASE}/documents/ingest`, { method: "POST", body: form })
  if (!res.ok) throw new Error("Upload failed")
  const data = (await res.json()) as { document_id: string }
  return data.document_id
}

export async function submitKindleFile(file: File): Promise<KindleIngestResult> {
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${API_BASE}/documents/ingest-kindle`, { method: "POST", body: form })
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new Error(data.detail ?? "Kindle import failed")
  }
  return (await res.json()) as KindleIngestResult
}

export async function submitUrl(url: string): Promise<string> {
  const res = await fetch(`${API_BASE}/documents/ingest-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new Error(data.detail ?? "Ingestion failed")
  }
  const data = (await res.json()) as { document_id: string }
  return data.document_id
}

export async function fetchIngestionStatus(docId: string): Promise<IngestionStatus> {
  const res = await fetch(`${API_BASE}/documents/${docId}/status`)
  if (!res.ok) throw new Error(`Status fetch failed (${res.status})`)
  return (await res.json()) as IngestionStatus
}
