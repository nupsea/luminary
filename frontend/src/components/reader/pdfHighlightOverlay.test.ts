import { describe, it, expect, beforeEach, vi } from "vitest"

// Stub minimal DOM APIs needed by the overlay utilities
function createMockElement(tag = "div"): any {
  const attrs: Record<string, string> = {}
  const children: any[] = []
  const style: Record<string, string> = {}
  return {
    tagName: tag.toUpperCase(),
    children,
    childNodes: children,
    style,
    setAttribute(k: string, v: string) { attrs[k] = v },
    getAttribute(k: string) { return attrs[k] ?? null },
    appendChild(child: any) { children.push(child); return child },
    replaceChildren(...nodes: any[]) { children.length = 0; children.push(...nodes) },
    remove() { /* no-op in isolation */ },
    querySelectorAll(selector: string) {
      // Simple attribute selector matching: [data-foo]
      const m = selector.match(/^\[([^\]]+)\]$/)
      if (!m) return []
      const attr = m[1]
      return children.filter((c: any) => c.getAttribute(attr) !== null)
    },
    querySelector(selector: string) {
      const all = this.querySelectorAll(selector)
      return all.length > 0 ? all[0] : null
    },
  }
}

// We import functions after stubbing if needed, but these are pure enough
import { clearOverlays, renderOverlayDivs, type OverlayRect } from "./pdfHighlightOverlay"

describe("renderOverlayDivs", () => {
  let container: any

  beforeEach(() => {
    container = createMockElement("div")
    // Stub document.createElement to return mock elements
    const stubDoc = {
      createElement(tag: string) {
        return createMockElement(tag)
      },
    }
    vi.stubGlobal("document", stubDoc)
  })

  it("creates divs for each rect with correct positioning", () => {
    const rects: OverlayRect[] = [
      { left: 10, top: 20, width: 100, height: 14 },
      { left: 10, top: 40, width: 80, height: 14 },
    ]

    renderOverlayDivs(container, rects, "rgba(255,255,0,0.4)", "data-search-highlight")

    expect(container.children.length).toBe(2)

    const div0 = container.children[0]
    expect(div0.getAttribute("data-search-highlight")).toBe("1")
    expect(div0.style.position).toBe("absolute")
    expect(div0.style.left).toBe("10px")
    expect(div0.style.top).toBe("20px")
    expect(div0.style.width).toBe("100px")
    expect(div0.style.height).toBe("14px")
    expect(div0.style.pointerEvents).toBe("none")
  })

  it("sets pointer-events auto when annotationId is provided", () => {
    const rects: OverlayRect[] = [{ left: 0, top: 0, width: 50, height: 12 }]
    renderOverlayDivs(container, rects, "yellow", "data-pdf-highlight", "ann-123")

    const div = container.children[0]
    expect(div.style.pointerEvents).toBe("auto")
    expect(div.style.cursor).toBe("pointer")
    expect(div.getAttribute("data-annotation-id")).toBe("ann-123")
  })

  it("marks active search match with data attribute", () => {
    const rects: OverlayRect[] = [{ left: 0, top: 0, width: 50, height: 12 }]
    renderOverlayDivs(container, rects, "orange", "data-search-highlight", undefined, true)

    const div = container.children[0]
    expect(div.getAttribute("data-active-search-match")).toBe("1")
  })

  it("does not mark non-active matches", () => {
    const rects: OverlayRect[] = [{ left: 0, top: 0, width: 50, height: 12 }]
    renderOverlayDivs(container, rects, "yellow", "data-search-highlight", undefined, false)

    const div = container.children[0]
    expect(div.getAttribute("data-active-search-match")).toBeNull()
  })

  it("handles empty rects array", () => {
    renderOverlayDivs(container, [], "yellow", "data-search-highlight")
    expect(container.children.length).toBe(0)
  })
})

describe("clearOverlays", () => {
  let container: any

  beforeEach(() => {
    container = createMockElement("div")
  })

  it("clears all children when no dataAttr specified", () => {
    container.appendChild(createMockElement("div"))
    container.appendChild(createMockElement("div"))
    expect(container.children.length).toBe(2)

    clearOverlays(container)
    expect(container.children.length).toBe(0)
  })

  it("clears only divs with the specified data attribute", () => {
    const search = createMockElement("div")
    search.setAttribute("data-search-highlight", "1")
    // Override remove to actually remove from parent
    search.remove = () => {
      const idx = container.children.indexOf(search)
      if (idx >= 0) container.children.splice(idx, 1)
    }
    container.appendChild(search)

    const annotation = createMockElement("div")
    annotation.setAttribute("data-pdf-highlight", "1")
    annotation.remove = () => {
      const idx = container.children.indexOf(annotation)
      if (idx >= 0) container.children.splice(idx, 1)
    }
    container.appendChild(annotation)

    clearOverlays(container, "data-search-highlight")
    expect(container.children.length).toBe(1)
    expect(container.children[0].getAttribute("data-pdf-highlight")).toBe("1")
  })

  it("handles empty container", () => {
    clearOverlays(container, "data-search-highlight")
    expect(container.children.length).toBe(0)
  })
})
