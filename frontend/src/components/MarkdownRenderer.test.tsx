import { describe, it, expect } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import { MarkdownRenderer } from "./MarkdownRenderer"
import { API_BASE } from "@/lib/config"

describe("MarkdownRenderer image resolution", () => {
  it("resolves relative image paths to the document asset endpoint when documentId is provided", () => {
    const md = "![RAG Architecture](images/horp_0101.png)"
    const html = renderToStaticMarkup(<MarkdownRenderer documentId="5a625e80-bbfa-497c">{md}</MarkdownRenderer>)

    expect(html).toContain(`src="${API_BASE}/documents/5a625e80-bbfa-497c/asset/images/horp_0101.png"`)
    expect(html).toContain('alt="RAG Architecture"')
  })

  it("leaves absolute http/https URLs untouched", () => {
    const md = "![Web](https://example.com/fig.png)\n\n![Other](http://example.org/photo.jpg)"
    const html = renderToStaticMarkup(<MarkdownRenderer documentId="doc-123">{md}</MarkdownRenderer>)

    expect(html).toContain('src="https://example.com/fig.png"')
    expect(html).toContain('src="http://example.org/photo.jpg"')
  })

  it("resolves __LUMINARY_IMG__ links to the local mirrored image endpoint", () => {
    const md = "![Mirrored](__LUMINARY_IMG__/doc-456/art.png)"
    const html = renderToStaticMarkup(<MarkdownRenderer>{md}</MarkdownRenderer>)

    expect(html).toContain(`src="${API_BASE}/images/local/doc-456/art.png"`)
  })

  it("renders mathematical formulas with KaTeX", () => {
    const md = "$$\n\\text{Attention}(Q, K, V) = \\text{softmax}\\left(\\frac{Q K^T}{\\sqrt{d_k}}\\right) V \\tag{1}\n$$"
    const html = renderToStaticMarkup(<MarkdownRenderer>{md}</MarkdownRenderer>)

    expect(html).toContain("katex")
    expect(html).toContain("katex-display")
  })
})

