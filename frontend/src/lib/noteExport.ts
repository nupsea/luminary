/**
 * Note export helpers: Markdown download (backend-rendered, matches vault
 * export format) and a print window for PDF via the browser's print dialog.
 */

import { toast } from "sonner"
import { API_BASE } from "@/lib/config"

export async function downloadNoteMarkdown(noteId: string): Promise<void> {
  const toastId = toast.loading("Preparing Markdown export...")
  try {
    const url = `${API_BASE}/notes/${noteId}/export?format=markdown`
    // Binary download: we need res.blob() + res.headers.get("content-disposition")
    // for the filename; apiClient's JSON path doesn't apply.
    const res = await fetch(url)
    if (!res.ok) throw new Error(`Export failed: ${res.status}`)
    const blob = await res.blob()
    const disposition = res.headers.get("content-disposition") ?? ""
    const match = /filename=([^\s;]+)/.exec(disposition)
    const filename = match ? match[1] : "note.md"
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
    toast.success("Markdown downloaded", { id: toastId })
  } catch (err) {
    toast.error(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`, {
      id: toastId,
    })
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

/** Wait until the rendered note (images, async mermaid diagrams) settles. */
export async function waitForRenderedAssets(root: HTMLElement, timeoutMs = 5000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  const images = Array.from(root.querySelectorAll("img"))
  const pending = images
    .filter((img) => !img.complete)
    .map(
      (img) =>
        new Promise<void>((resolve) => {
          img.onload = () => resolve()
          img.onerror = () => resolve()
        }),
    )
  await Promise.race([
    Promise.all(pending),
    new Promise((resolve) => setTimeout(resolve, Math.max(0, deadline - Date.now()))),
  ])
  // Mermaid renders asynchronously (dynamic import + render); poll until its
  // "Rendering diagram..." placeholders are gone or the deadline passes.
  while (Date.now() < deadline && root.textContent?.includes("Rendering diagram...")) {
    await new Promise((resolve) => setTimeout(resolve, 150))
  }
}

/**
 * Print the rendered note through a hidden same-origin iframe, where the
 * browser print dialog offers "Save as PDF". An iframe (unlike window.open)
 * is never popup-blocked, which matters because printing starts from an async
 * effect, not directly from the click. The app's stylesheets are copied so
 * the output matches the reading view (light theme).
 */
export async function printNoteHtml(title: string, bodyHtml: string): Promise<void> {
  const iframe = document.createElement("iframe")
  iframe.setAttribute("aria-hidden", "true")
  iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden"
  document.body.appendChild(iframe)
  const frameDoc = iframe.contentDocument
  const frameWin = iframe.contentWindow
  if (!frameDoc || !frameWin) {
    iframe.remove()
    toast.error("Could not prepare the print view")
    return
  }

  const styles = Array.from(document.querySelectorAll('style, link[rel="stylesheet"]'))
    .map((node) => node.outerHTML)
    .join("\n")
  const loaded = new Promise<void>((resolve) => {
    let settled = false
    const done = () => {
      if (settled) return
      settled = true
      resolve()
    }
    // onload fires once the written document's subresources (stylesheet
    // links, images) settle; the timeout covers frames where it never fires.
    iframe.onload = done
    setTimeout(done, 2000)
  })
  frameDoc.open()
  frameDoc.write(`<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>${escapeHtml(title || "Note")}</title>
${styles}
<style>
  body { margin: 0 auto; max-width: 794px; padding: 2.5rem; background: #fff; }
  @media print { body { padding: 0; } }
</style>
</head>
<body>
${title ? `<h1>${escapeHtml(title)}</h1>` : ""}
${bodyHtml}
</body>
</html>`)
  frameDoc.close()
  await loaded

  // Browsers name the saved PDF after the top document's title, not the frame's.
  const previousTitle = document.title
  if (title) document.title = title
  let cleaned = false
  const cleanup = () => {
    if (cleaned) return
    cleaned = true
    document.title = previousTitle
    iframe.remove()
  }
  frameWin.addEventListener("afterprint", () => setTimeout(cleanup, 100))
  try {
    frameWin.focus()
    frameWin.print()
  } finally {
    // print() usually blocks until the dialog closes; the delay covers
    // engines where it returns immediately.
    setTimeout(cleanup, 2000)
  }
}
