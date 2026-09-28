import { afterEach, describe, expect, it } from "vitest"

import { isWithheldImage, readShellClipboardImage } from "./noteAssets"

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

function withShell(invoke: Invoke | null) {
  const w = globalThis as unknown as { window?: unknown }
  if (!w.window) w.window = w
  const target = w.window as { __TAURI__?: unknown }
  if (invoke === null) delete target.__TAURI__
  else target.__TAURI__ = { core: { invoke } }
}

function pasted(types: string[], text = ""): DataTransfer {
  return { types, getData: (t: string) => (t === "text/plain" ? text : "") } as unknown as DataTransfer
}

afterEach(() => withShell(null))

describe("isWithheldImage", () => {
  // What WKWebView hands the page for a pasted macOS screenshot (public.heic + public.tiff).
  const screenshot = pasted(["Files"])

  it("is true for a screenshot paste in the desktop shell", () => {
    withShell(async () => null)
    expect(isWithheldImage(screenshot)).toBe(true)
  })

  it("is false outside the shell, where nothing could read it", () => {
    expect(isWithheldImage(screenshot)).toBe(false)
  })

  it("leaves text pastes to the editor", () => {
    withShell(async () => null)
    expect(isWithheldImage(pasted(["text/plain"], "hello"))).toBe(false)
    expect(isWithheldImage(pasted(["Files", "text/plain"], "report.pdf"))).toBe(false)
  })
})

describe("readShellClipboardImage", () => {
  it("is null without a shell", async () => {
    await expect(readShellClipboardImage()).resolves.toBeNull()
  })

  it("wraps the shell's PNG bytes as an uploadable file", async () => {
    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47])
    const calls: string[] = []
    withShell(async (cmd) => {
      calls.push(cmd)
      return png.buffer
    })
    const file = await readShellClipboardImage()
    expect(calls).toEqual(["read_clipboard_image"])
    expect(file?.type).toBe("image/png")
    expect(new Uint8Array(await file!.arrayBuffer())).toEqual(png)
  })

  it("surfaces the shell's refusal instead of inserting nothing", async () => {
    withShell(async () => {
      throw "the clipboard holds no image"
    })
    await expect(readShellClipboardImage()).rejects.toBe("the clipboard holds no image")
  })
})
