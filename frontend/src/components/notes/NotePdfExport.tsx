/**
 * Offscreen render host for PDF export. Mounts the note through the real
 * MarkdownRenderer (so mermaid, math, and images render), waits for async
 * assets, then opens a print window where the browser offers "Save as PDF".
 * Mount it only while an export is in flight; it unmounts itself via onDone.
 */

import { useEffect, useRef } from "react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { printNoteHtml, waitForRenderedAssets } from "@/lib/noteExport"

export interface NotePdfExportProps {
  title: string
  content: string
  onDone: () => void
}

export function NotePdfExport({ title, content, onDone }: NotePdfExportProps) {
  const hostRef = useRef<HTMLDivElement>(null)

  // StrictMode-safe: the dev double-mount cancels the first run via cleanup
  // (the settle delay guarantees it never reaches print), and the surviving
  // run prints and calls onDone. No "already started" ref -- refs persist
  // across the StrictMode remount and would permanently skip the second run.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      await new Promise((resolve) => setTimeout(resolve, 100))
      if (cancelled) return
      const host = hostRef.current
      if (host) {
        await waitForRenderedAssets(host)
        if (cancelled) return
        await printNoteHtml(title, host.innerHTML)
      }
      onDone()
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div aria-hidden className="pointer-events-none fixed left-[-10000px] top-0 w-[794px]">
      <div ref={hostRef}>
        <MarkdownRenderer serif>{content}</MarkdownRenderer>
      </div>
    </div>
  )
}
