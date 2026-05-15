import { API_BASE } from "@/lib/config"

export interface NoteAssetUpload {
  path: string
  filename: string
}

export async function uploadNoteAsset(file: File): Promise<NoteAssetUpload> {
  const formData = new FormData()
  formData.append("file", file)

  const res = await fetch(`${API_BASE}/images/notes`, {
    method: "POST",
    body: formData,
  })
  if (!res.ok) throw new Error(`POST /images/notes failed: ${res.status}`)
  return res.json() as Promise<NoteAssetUpload>
}

export function resolveLuminaryAssetUrl(path: string): string {
  return path.replace(/^__LUMINARY_IMG__\//, `${API_BASE}/images/local/`)
}

