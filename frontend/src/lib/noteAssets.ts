import { API_BASE } from "@/lib/config"

export interface NoteAssetUpload {
  path: string
  filename: string
}

export async function uploadNoteAsset(file: File): Promise<NoteAssetUpload> {
  const formData = new FormData()
  let filename = file.name
  if (!filename || filename === "blob" || !/\.[a-zA-Z0-9]+$/.test(filename)) {
    const subtype = file.type ? file.type.split("/")[1] || "png" : "png"
    const ext = subtype === "jpeg" ? "jpg" : subtype
    filename = `screenshot.${ext}`
  }
  formData.append("file", file, filename)

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

