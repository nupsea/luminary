import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useAudioRecorder } from "./useAudioRecorder"

const apiPost = vi.fn()
vi.mock("@/lib/apiClient", () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
  detailFromError: (_e: unknown, fallback: string) => new Error(fallback),
}))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn() } }))

class FakeRecorder {
  static made: FakeRecorder[] = []
  static isTypeSupported = (t: string) => t === "audio/webm;codecs=opus"
  mimeType: string
  state = "inactive"
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => Promise<void>) | null = null
  onerror: (() => void) | null = null
  constructor(_stream: unknown, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? ""
    FakeRecorder.made.push(this)
  }
  start() {
    this.state = "recording"
  }
  emit(text: string) {
    this.ondataavailable?.({ data: new Blob([text.padEnd(600, ".")]) })
  }
  async stop() {
    this.state = "inactive"
    await this.onstop?.()
  }
}

function hook() {
  let api!: ReturnType<typeof useAudioRecorder>
  function Harness() {
    api = useAudioRecorder({ onTranscribed: () => {} })
    return null
  }
  renderToStaticMarkup(<Harness />)
  return api
}

let getUserMedia: ReturnType<typeof vi.fn>

beforeEach(() => {
  FakeRecorder.made = []
  apiPost.mockReset().mockResolvedValue({ text: "hello" })
  getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: () => {} }] })
  vi.stubGlobal("navigator", { language: "en-GB", mediaDevices: { getUserMedia } })
  vi.stubGlobal("MediaRecorder", FakeRecorder)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function uploaded(call: number): Promise<string> {
  const form = apiPost.mock.calls[call][1] as FormData
  return (form.get("file") as Blob).text()
}

describe("useAudioRecorder", () => {
  it("starts one recorder when clicked again during the permission prompt", async () => {
    const api = hook()
    await Promise.all([api.startRecording(), api.startRecording()])
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(FakeRecorder.made).toHaveLength(1)
  })

  it("uploads only the chunks of its own recording", async () => {
    // Shared chunks let a stray recorder's header-less data lead the next
    // upload, which the decoder rejects as invalid WebM.
    const api = hook()
    await api.startRecording()
    const first = FakeRecorder.made[0]
    first.emit("first")
    await first.stop()

    await api.startRecording()
    const second = FakeRecorder.made[1]
    first.emit("stray")
    second.emit("second")
    await second.stop()

    expect(await uploaded(0)).toMatch(/^first/)
    expect(await uploaded(1)).toMatch(/^second/)
    expect(await uploaded(1)).not.toContain("stray")
  })

  it("names the upload after the container the browser wrote", async () => {
    const api = hook()
    await api.startRecording()
    const rec = FakeRecorder.made[0]
    rec.mimeType = "audio/ogg;codecs=opus"
    rec.emit("x")
    await rec.stop()
    const form = apiPost.mock.calls[0][1] as FormData
    expect((form.get("file") as File).name).toBe("voice_recording.ogg")
  })

  it("sends the UI language as the transcription hint", async () => {
    const api = hook()
    await api.startRecording()
    const rec = FakeRecorder.made[0]
    rec.emit("x")
    await rec.stop()
    const form = apiPost.mock.calls[0][1] as FormData
    expect(form.get("language")).toBe("en")
  })
})
