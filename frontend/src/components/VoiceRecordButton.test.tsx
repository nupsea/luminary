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
  it("offers the install, not a recording, on an install with no transcriber", () => {
    // The bundle ships no faster-whisper (GPL). A hidden mic left users unaware
    // dictation existed; a recording mic would record and then fail.
    const out = html({ dictation: { available: false, requires: ["transcription"] } })
    expect(out).toContain("Dictation needs speech to text")
    expect(out).not.toContain("Dictate with voice")
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
