import { API_BASE } from "@/lib/config"

export interface NoteAssetUpload {
  path: string
  filename: string
}

async function normalizeImageFile(file: File): Promise<File> {
  const isStandardWebImage =
    file.type === "image/png" ||
    file.type === "image/jpeg" ||
    file.type === "image/webp" ||
    file.type === "image/svg+xml" ||
    file.type === "image/gif"

  if (isStandardWebImage && !file.name.toLowerCase().endsWith(".tiff") && !file.name.toLowerCase().endsWith(".tif")) {
    return file
  }

  // Attempt to convert non-standard images (e.g. macOS TIFF screenshots) to PNG
  try {
    if (typeof createImageBitmap !== "undefined" && typeof document !== "undefined") {
      const bitmap = await createImageBitmap(file)
      const canvas = document.createElement("canvas")
      canvas.width = bitmap.width
      canvas.height = bitmap.height
      const ctx = canvas.getContext("2d")
      if (ctx) {
        ctx.drawImage(bitmap, 0, 0)
        const blob = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob(resolve, "image/png"),
        )
        if (blob) {
          const baseName = file.name ? file.name.replace(/\.[a-zA-Z0-9]+$/, "") : "screenshot"
          return new File([blob], `${baseName}.png`, { type: "image/png" })
        }
      }
    }
  } catch {
    // If conversion fails (e.g. headless environment), fall back to original file
  }

  return file
}

export async function uploadNoteAsset(file: File): Promise<NoteAssetUpload> {
  const normalized = await normalizeImageFile(file)
  const formData = new FormData()
  let filename = normalized.name
  if (!filename || filename === "blob" || !/\.[a-zA-Z0-9]+$/.test(filename)) {
    const subtype = normalized.type ? normalized.type.split("/")[1] || "png" : "png"
    const ext = subtype === "jpeg" ? "jpg" : subtype
    filename = `screenshot.${ext}`
  }
  formData.append("file", normalized, filename)

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

