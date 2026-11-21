import { afterEach, describe, expect, it, vi } from "vitest"

import { configureTransport } from "./apiClient"
import { API_BASE } from "./config"
import { fetchNoteAsset, isWithheldImage, readShellClipboardImage, resolveLuminaryAssetUrl } from "./noteAssets"

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

describe("note asset URLs under a relative base", () => {
  afterEach(() => configureTransport({ baseUrl: API_BASE }))

  // Public mode serves the API under /api; feeding a resolved URL back to apiFetch made /api/api/...
  it("prefixes the base once, for src= and for a fetch", async () => {
    const stub = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    configureTransport({ baseUrl: "/api", fetch: stub as unknown as typeof fetch })
    expect(resolveLuminaryAssetUrl("__LUMINARY_IMG__/notes/a.svg")).toBe("/api/images/local/notes/a.svg")
    await fetchNoteAsset("__LUMINARY_IMG__/notes/a.excalidraw.json", { cache: "no-store" })
    expect(stub.mock.calls[0][0]).toBe("/api/images/local/notes/a.excalidraw.json")
    expect(stub.mock.calls[0][1]).toMatchObject({ cache: "no-store" })
  })

  it("leaves a path without the asset token unchanged", () => {
    configureTransport({ baseUrl: "/api" })
    for (const path of ["data:image/svg+xml;base64,AAAA", "blob:http://localhost/x", "foo.svg"]) {
      expect(resolveLuminaryAssetUrl(path)).toBe(path)
    }
  })

  it("drops a trailing slash from the base", () => {
    configureTransport({ baseUrl: "/api/" })
    expect(resolveLuminaryAssetUrl("__LUMINARY_IMG__/a.png")).toBe("/api/images/local/a.png")
  })
})
