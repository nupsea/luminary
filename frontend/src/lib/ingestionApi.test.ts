import { beforeEach, describe, expect, it, vi } from "vitest"

const apiPost = vi.fn()
const renderPage = vi.fn()

vi.mock("@/lib/apiClient", () => ({
  apiGet: vi.fn(),
  apiPost: (...args: unknown[]) => apiPost(...args),
}))
vi.mock("@/lib/pageRender", () => ({ renderPage: (url: string) => renderPage(url) }))

import { savedFromUrl, submitUrl } from "./ingestionApi"

beforeEach(() => {
  apiPost.mockReset().mockResolvedValue({ document_id: "doc-1", warnings: [] })
  renderPage.mockReset().mockResolvedValue({ html: null, state: "unavailable" })
})

describe("savedFromUrl", () => {
  it("reads the address a Chromium browser stamps into a saved page", () => {
    const html = "<!DOCTYPE html>\n<!-- saved from url=(0043)https://ghost.test/eighteen-month-recap/ -->\n<html>"
    expect(savedFromUrl(html)).toBe("https://ghost.test/eighteen-month-recap/")
  })

  it("is null for a page without the stamp", () => {
    expect(savedFromUrl("<html><!-- a comment --></html>")).toBeNull()
  })
})

describe("submitUrl", () => {
  it("sends a saved page as the page HTML instead of rendering", async () => {
    await submitUrl("https://ghost.test/post/", "<html>signed in</html>")
    expect(renderPage).not.toHaveBeenCalled()
    expect(apiPost).toHaveBeenCalledWith(
      "/documents/ingest-url",
      expect.objectContaining({ rendered_html: "<html>signed in</html>", render_state: "saved" }),
    )
  })

  it("renders when no page was saved", async () => {
    await submitUrl("https://ghost.test/post/")
    expect(renderPage).toHaveBeenCalledWith("https://ghost.test/post/")
    expect(apiPost.mock.calls[0][1]).not.toHaveProperty("rendered_html")
  })
})
