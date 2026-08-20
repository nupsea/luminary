import { afterEach, describe, expect, it, vi } from "vitest"

import { canRender, renderPage } from "./pageRender"

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

/** Stand in for the desktop shell. Absent everywhere else, which is the point. */
function withShell(invoke: Invoke | null) {
  const w = globalThis as unknown as { window?: unknown; __TAURI__?: unknown }
  if (!w.window) w.window = w
  const target = w.window as { __TAURI__?: unknown }
  if (invoke === null) delete target.__TAURI__
  else target.__TAURI__ = { core: { invoke } }
}

afterEach(() => withShell(null))

describe("canRender", () => {
  it("is false without a desktop shell", () => {
    withShell(null)
    expect(canRender()).toBe(false)
  })

  it("is true when the shell exposes invoke", () => {
    withShell(async () => "<html></html>")
    expect(canRender()).toBe(true)
  })
})

describe("renderPage", () => {
  it("reports unavailable without a shell rather than throwing", async () => {
    withShell(null)
    await expect(renderPage("https://example.test/a")).resolves.toEqual({
      html: null,
      state: "unavailable",
    })
  })

  it("returns the rendered DOM", async () => {
    withShell(async () => "<html><body>rendered</body></html>")
    await expect(renderPage("https://example.test/a")).resolves.toMatchObject({
      html: expect.stringContaining("rendered"),
      state: "ok",
    })
  })

  it("passes the url through to the shell command", async () => {
    const invoke = vi.fn(async () => "<html></html>")
    withShell(invoke)
    await renderPage("https://example.test/a")
    expect(invoke).toHaveBeenCalledWith("render_page", { url: "https://example.test/a" })
  })

  it("reports failed, distinctly from unavailable, when the shell rejects", async () => {
    withShell(async () => {
      throw new Error("the page did not settle in time")
    })
    await expect(renderPage("https://example.test/a")).resolves.toEqual({
      html: null,
      state: "failed",
      // The reason travels with the outcome. An ACL rejection reports itself
      // only to the page, so a failure whose detail stopped here was
      // indistinguishable from a page that needed no rendering.
      detail: "Error: the page did not settle in time",
    })
  })

  it("treats an empty render as no render", async () => {
    withShell(async () => "   ")
    await expect(renderPage("https://example.test/a")).resolves.toMatchObject({ html: null })
  })

  it("treats a non-string answer as no render", async () => {
    withShell(async () => 42)
    await expect(renderPage("https://example.test/a")).resolves.toMatchObject({ html: null })
  })
})
