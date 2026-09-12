import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { VoiceRecordButton } from "./VoiceRecordButton"
import type { Capabilities } from "@/lib/setupApi"

function html(caps: Partial<Capabilities> | undefined) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (caps) qc.setQueryData(["setup", "capabilities"], caps)
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <VoiceRecordButton onTranscribed={() => {}} label="Dictate" />
    </QueryClientProvider>,
  )
}

describe("VoiceRecordButton", () => {
  it("is not offered on an install with no transcriber", () => {
    // The distributed bundle ships no faster-whisper: it pulls GPL code, so it
    // is a component the user installs afterwards. Offering the mic before then
    // takes a recording and answers with a `uv sync` line.
    expect(html({ dictation: { available: false, requires: ["transcription"] } })).toBe("")
  })

  it("is offered once the transcriber is installed", () => {
    expect(html({ dictation: { available: true, requires: [] } })).toContain("Dictate")
  })

  it("is offered while capabilities are still unknown", () => {
    // A slow /setup/capabilities must not hide a working button; the backend
    // refuses what it cannot do anyway.
    expect(html(undefined)).toContain("Dictate")
  })

  it("supports icon variant without text label", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(["setup", "capabilities"], { dictation: { available: true, requires: [] } })
    const out = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <VoiceRecordButton onTranscribed={() => {}} variant="icon" size="sm" />
      </QueryClientProvider>,
    )
    expect(out).toContain("<button")
    expect(out).toContain("h-7 w-7")
    expect(out).not.toContain("<span>")
  })
})
