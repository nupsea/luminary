import { describe, expect, it, vi } from "vitest"
import {
  buildFontTOC,
  flattenOutline,
  resolveDestPage,
  resolveOutline,
  shouldUseOutline,
  type OutlineEntry,
} from "./pdfTocUtils"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal pdfjs PDFDocumentProxy mock. */
function makeDoc(overrides: Record<string, unknown> = {}) {
  return {
    numPages: 100,
    getDestination: vi.fn(),
    getPageIndex: vi.fn(),
    getPage: vi.fn(),
    ...overrides,
  } as unknown as import("pdfjs-dist").PDFDocumentProxy
}

/** Build a mock page whose text content contains the given items. */
function makePage(items: { str: string; height: number; transform?: number[] }[]) {
  return {
    getTextContent: vi.fn().mockResolvedValue({
      items: items.map(i => ({
        str: i.str,
        height: i.height,
        transform: i.transform ?? [1, 0, 0, i.height, 0, 0],
      })),
    }),
  }
}

// ---------------------------------------------------------------------------
// shouldUseOutline
// ---------------------------------------------------------------------------

describe("shouldUseOutline", () => {
  it("returns false when outline is empty", () => {
    expect(shouldUseOutline(0, 0)).toBe(false)
    expect(shouldUseOutline(0, 50)).toBe(false)
  })

  it("returns true when no backend sections exist", () => {
    expect(shouldUseOutline(1, 0)).toBe(true)
    expect(shouldUseOutline(20, 0)).toBe(true)
  })

  it("returns true when outline has more entries than backend sections", () => {
    expect(shouldUseOutline(30, 10)).toBe(true)
  })

  it("returns true when outline matches backend sections exactly", () => {
    expect(shouldUseOutline(15, 15)).toBe(true)
  })

  it("returns false when outline has fewer entries than backend sections (Big Data shrink case)", () => {
    expect(shouldUseOutline(15, 40)).toBe(false)
  })

  it("returns true for Learning-how-to-learn: font TOC richer than sparse backend", () => {
    expect(shouldUseOutline(20, 5)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// flattenOutline
// ---------------------------------------------------------------------------

describe("flattenOutline", () => {
  it("returns empty array for empty input", () => {
    expect(flattenOutline([])).toEqual([])
  })

  it("returns flat list unchanged when no children", () => {
    const entries: OutlineEntry[] = [
      { title: "Ch1", page: 1, level: 1, children: [] },
      { title: "Ch2", page: 20, level: 1, children: [] },
    ]
    expect(flattenOutline(entries)).toEqual(entries)
  })

  it("flattens one level of children in DFS order", () => {
    const entries: OutlineEntry[] = [
      {
        title: "Ch1", page: 1, level: 1, children: [
          { title: "S1.1", page: 5, level: 2, children: [] },
          { title: "S1.2", page: 10, level: 2, children: [] },
        ],
      },
      { title: "Ch2", page: 20, level: 1, children: [] },
    ]
    const flat = flattenOutline(entries)
    expect(flat.map(e => e.title)).toEqual(["Ch1", "S1.1", "S1.2", "Ch2"])
  })

  it("flattens deeply nested children", () => {
    const entries: OutlineEntry[] = [
      {
        title: "Part I", page: 1, level: 1, children: [
          {
            title: "Ch1", page: 5, level: 2, children: [
              { title: "S1.1", page: 8, level: 3, children: [] },
            ],
          },
        ],
      },
    ]
    const flat = flattenOutline(entries)
    expect(flat.map(e => e.title)).toEqual(["Part I", "Ch1", "S1.1"])
    expect(flat.map(e => e.level)).toEqual([1, 2, 3])
  })
})

// ---------------------------------------------------------------------------
// resolveDestPage
// ---------------------------------------------------------------------------

describe("resolveDestPage", () => {
  it("resolves a RefProxy destination (standard pdfjs format)", async () => {
    const ref = { num: 9, gen: 0 }
    const doc = makeDoc({ getPageIndex: vi.fn().mockResolvedValue(9) })
    // dest array: [RefProxy, /XYZ, x, y, zoom]
    const page = await resolveDestPage(doc, [ref, "XYZ", 0, 800, null])
    expect(page).toBe(10) // 0-based index 9 → 1-based 10
  })

  it("resolves an integer destination (many PDF generators use this)", async () => {
    const doc = makeDoc()
    // dest[0] is an integer — 0-based index 24
    const page = await resolveDestPage(doc, [24, "XYZ", 0, 800, null])
    expect(page).toBe(25) // 0-based 24 → 1-based 25
    expect((doc as any).getPageIndex).not.toHaveBeenCalled()
  })

  it("returns -1 for a null dest[0] (current-page reference)", async () => {
    const doc = makeDoc()
    const page = await resolveDestPage(doc, [null, "XYZ", 0, 0, null])
    expect(page).toBe(-1)
  })

  it("resolves a named destination string", async () => {
    const ref = { num: 4, gen: 0 }
    const doc = makeDoc({
      getDestination: vi.fn().mockResolvedValue([ref, "XYZ", 0, 800, null]),
      getPageIndex: vi.fn().mockResolvedValue(4),
    })
    const page = await resolveDestPage(doc, "chapter-1")
    expect((doc as any).getDestination).toHaveBeenCalledWith("chapter-1")
    expect(page).toBe(5)
  })

  it("returns -1 when named destination is not found (getDestination returns null)", async () => {
    const doc = makeDoc({ getDestination: vi.fn().mockResolvedValue(null) })
    const page = await resolveDestPage(doc, "missing-dest")
    expect(page).toBe(-1)
  })

  it("returns -1 for an empty dest array", async () => {
    const doc = makeDoc()
    const page = await resolveDestPage(doc, [])
    expect(page).toBe(-1)
  })
})

// ---------------------------------------------------------------------------
// resolveOutline
// ---------------------------------------------------------------------------

describe("resolveOutline", () => {
  it("resolves all entries when all dests are valid", async () => {
    const doc = makeDoc({ getPageIndex: vi.fn().mockResolvedValue(9) })
    const items = [
      { title: "Ch1", dest: [{ num: 9, gen: 0 }, "XYZ"], items: [] },
      { title: "Ch2", dest: [{ num: 9, gen: 0 }, "XYZ"], items: [] },
    ]
    const result = await resolveOutline(doc, items, 1)
    expect(result).toHaveLength(2)
    expect(result[0]).toMatchObject({ title: "Ch1", page: 10, level: 1 })
    expect(result[1]).toMatchObject({ title: "Ch2", page: 10, level: 1 })
  })

  it("keeps entries with page = 0 when dest cannot be resolved (never drops)", async () => {
    const doc = makeDoc({ getDestination: vi.fn().mockResolvedValue(null) })
    const items = [
      { title: "Unresolvable", dest: "missing", items: [] },
      { title: "No dest", dest: null, items: [] },
    ]
    const result = await resolveOutline(doc, items, 1)
    expect(result).toHaveLength(2)
    expect(result[0]).toMatchObject({ title: "Unresolvable", page: 0 })
    expect(result[1]).toMatchObject({ title: "No dest", page: 0 })
  })

  it("recurses into children and sets correct levels", async () => {
    const doc = makeDoc({ getPageIndex: vi.fn().mockImplementation((ref: any) => ref.num) })
    const items = [
      {
        title: "Ch1", dest: [{ num: 4, gen: 0 }, "XYZ"], items: [
          { title: "S1.1", dest: [{ num: 9, gen: 0 }, "XYZ"], items: [] },
        ],
      },
    ]
    const result = await resolveOutline(doc, items, 1)
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ title: "Ch1", page: 5, level: 1 })
    expect(result[0].children).toHaveLength(1)
    expect(result[0].children[0]).toMatchObject({ title: "S1.1", page: 10, level: 2 })
  })

  it("uses integer dest[0] directly without calling getPageIndex", async () => {
    const doc = makeDoc()
    const items = [{ title: "Ch1", dest: [19, "XYZ"], items: [] }]
    const result = await resolveOutline(doc, items, 1)
    expect(result[0].page).toBe(20)
    expect((doc as any).getPageIndex).not.toHaveBeenCalled()
  })

  it("keeps parent with page = 0 when its dest is null but still recurses children", async () => {
    const doc = makeDoc({ getPageIndex: vi.fn().mockResolvedValue(14) })
    const items = [
      {
        title: "Part I", dest: null, items: [
          { title: "Ch1", dest: [{ num: 14, gen: 0 }, "XYZ"], items: [] },
        ],
      },
    ]
    const result = await resolveOutline(doc, items, 1)
    // Part I kept with page = 0, Ch1 resolved correctly
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ title: "Part I", page: 0 })
    expect(result[0].children).toHaveLength(1)
    expect(result[0].children[0]).toMatchObject({ title: "Ch1", page: 15 })
  })

  it("flattens cleanly after resolve — full book structure survives", async () => {
    const doc = makeDoc({ getPageIndex: vi.fn().mockImplementation((ref: any) => ref.num - 1) })
    const items = [
      {
        title: "Part I", dest: null, items: [
          { title: "Ch1", dest: [{ num: 10, gen: 0 }], items: [] },
          { title: "Ch2", dest: [{ num: 30, gen: 0 }], items: [] },
        ],
      },
      {
        title: "Part II", dest: null, items: [
          { title: "Ch3", dest: [{ num: 60, gen: 0 }], items: [] },
        ],
      },
    ]
    const resolved = await resolveOutline(doc, items, 1)
    const flat = flattenOutline(resolved).filter(e => e.page > 0).sort((a, b) => a.page - b.page)
    expect(flat.map(e => e.title)).toEqual(["Ch1", "Ch2", "Ch3"])
    expect(flat.map(e => e.page)).toEqual([10, 30, 60])
  })
})

// ---------------------------------------------------------------------------
// buildFontTOC
// ---------------------------------------------------------------------------

describe("buildFontTOC", () => {
  it("returns empty array for a doc with no text", async () => {
    const doc = makeDoc({
      numPages: 10,
      getPage: vi.fn().mockResolvedValue(makePage([])),
    })
    const result = await buildFontTOC(doc, () => false)
    expect(result).toEqual([])
  })

  it("returns empty array when cancelled immediately", async () => {
    const doc = makeDoc({ numPages: 5 })
    const result = await buildFontTOC(doc, () => true)
    expect(result).toEqual([])
    expect((doc as any).getPage).not.toHaveBeenCalled()
  })

  it("picks up heading-sized items and ignores body text", async () => {
    // Body text: size 12. Headings: size 24. Threshold = 12 * 1.15 = 13.8
    const bodyItem = (str: string) => ({ str, height: 12, transform: [1, 0, 0, 12, 0, 0] })
    const headingItem = (str: string) => ({ str, height: 24, transform: [1, 0, 0, 24, 0, 0] })

    // 20 pages. Heading on p10, p15 (gap ≥ 2 → survive). Body text on all pages.
    const pages: Record<number, ReturnType<typeof makePage>> = {}
    for (let p = 1; p <= 20; p++) {
      const items = [bodyItem(`Body text on page ${p}`), bodyItem(`More body ${p}`)]
      if (p === 10) items.push(headingItem("Chapter One"))
      if (p === 15) items.push(headingItem("Chapter Two"))
      pages[p] = makePage(items)
    }
    const doc = makeDoc({
      numPages: 20,
      getPage: vi.fn().mockImplementation((p: number) => Promise.resolve(pages[p])),
    })

    const result = await buildFontTOC(doc, () => false)
    const titles = result.map(e => e.title)
    expect(titles).toContain("Chapter One")
    expect(titles).toContain("Chapter Two")
  })

  it("stage 1: removes early-zone duplicates (printed TOC entries)", async () => {
    // 100-page book. earlyZone = max(5, ceil(100 * 0.12)) = 12.
    // "Chapter One" appears on page 5 (printed TOC) and page 40 (real heading).
    // "Chapter Two" appears on page 6 (printed TOC) and page 70 (real heading).
    // Both early-page instances should be dropped; later pages kept.
    const bodyItem = (str: string) => ({ str, height: 10 })
    const headingItem = (str: string) => ({ str, height: 20 })

    const pages: Record<number, ReturnType<typeof makePage>> = {}
    for (let p = 1; p <= 100; p++) {
      const items = [bodyItem(`body ${p}`)]
      if (p === 5) items.push(headingItem("Chapter One"))
      if (p === 6) items.push(headingItem("Chapter Two"))
      if (p === 40) items.push(headingItem("Chapter One"))
      if (p === 70) items.push(headingItem("Chapter Two"))
      pages[p] = makePage(items)
    }
    const doc = makeDoc({
      numPages: 100,
      getPage: vi.fn().mockImplementation((p: number) => Promise.resolve(pages[p])),
    })

    const result = await buildFontTOC(doc, () => false)
    const byPage = Object.fromEntries(result.map(e => [e.page, e.title]))
    expect(byPage[40]).toBe("Chapter One")
    expect(byPage[70]).toBe("Chapter Two")
    // Early duplicates should be absent
    expect(result.some(e => e.page === 5)).toBe(false)
    expect(result.some(e => e.page === 6)).toBe(false)
  })

  it("stage 2: removes pages with ≥3 heading candidates (TOC list pages)", async () => {
    // Page 8 has 4 heading-sized items — a list/TOC page, all 4 should be removed.
    // Page 50 has 1 heading — a real content heading, should survive.
    const bodyItem = (str: string) => ({ str, height: 10 })
    const headingItem = (str: string) => ({ str, height: 20 })

    const pages: Record<number, ReturnType<typeof makePage>> = {}
    for (let p = 1; p <= 100; p++) {
      const items = [bodyItem(`body ${p}`)]
      if (p === 8) {
        items.push(headingItem("TOC Entry A"), headingItem("TOC Entry B"),
          headingItem("TOC Entry C"), headingItem("TOC Entry D"))
      }
      if (p === 50) items.push(headingItem("Real Chapter"))
      pages[p] = makePage(items)
    }
    const doc = makeDoc({
      numPages: 100,
      getPage: vi.fn().mockImplementation((p: number) => Promise.resolve(pages[p])),
    })

    const result = await buildFontTOC(doc, () => false)
    expect(result.some(e => e.page === 8)).toBe(false)
    expect(result.some(e => e.title === "Real Chapter")).toBe(true)
  })

  it("stage 3: removes headings with nearest neighbour < 2 pages (running headers)", async () => {
    // Pages 20 and 21 both have a heading — they're 1 page apart, both should be removed.
    // Pages 40 and 50 are 10 apart — both should survive.
    const bodyItem = (str: string) => ({ str, height: 10 })
    const headingItem = (str: string) => ({ str, height: 20 })

    const pages: Record<number, ReturnType<typeof makePage>> = {}
    for (let p = 1; p <= 100; p++) {
      const items = [bodyItem(`body ${p}`)]
      if (p === 20) items.push(headingItem("Running Header A"))
      if (p === 21) items.push(headingItem("Running Header B"))
      if (p === 40) items.push(headingItem("Real Section A"))
      if (p === 50) items.push(headingItem("Real Section B"))
      pages[p] = makePage(items)
    }
    const doc = makeDoc({
      numPages: 100,
      getPage: vi.fn().mockImplementation((p: number) => Promise.resolve(pages[p])),
    })

    const result = await buildFontTOC(doc, () => false)
    const titles = result.map(e => e.title)
    expect(titles).not.toContain("Running Header A")
    expect(titles).not.toContain("Running Header B")
    expect(titles).toContain("Real Section A")
    expect(titles).toContain("Real Section B")
  })

  it("assigns level 1 to larger headings and level 2 to smaller sub-headings", async () => {
    // Three heading size groups: 24 (chapters), 18 (sections), 14 (sub-sections).
    // Body: 10. Threshold = 10 * 1.15 = 11.5 — all three heading sizes pass.
    // sizeSet desc = [24, 18, 14]. Gaps: 24→18 = 6 (largest), 18→14 = 4.
    // Algorithm: splitSize = 18 (lower bound of largest gap).
    // Level rule: size >= 18 → 1, size < 18 → 2.
    // So: 24 → L1, 18 → L1, 14 → L2.
    const bodyItem = (str: string) => ({ str, height: 10 })
    const h1Item = (str: string) => ({ str, height: 24 })
    const h2Item = (str: string) => ({ str, height: 18 })
    const h3Item = (str: string) => ({ str, height: 14 })

    const pages: Record<number, ReturnType<typeof makePage>> = {}
    for (let p = 1; p <= 100; p++) {
      const items = [bodyItem(`body ${p}`)]
      if (p === 20) items.push(h1Item("Big Chapter"))
      if (p === 30) items.push(h2Item("Medium Section"))
      if (p === 40) items.push(h3Item("Small Sub-section"))
      if (p === 60) items.push(h1Item("Another Chapter"))
      if (p === 75) items.push(h3Item("Another Sub-section"))
      pages[p] = makePage(items)
    }
    const doc = makeDoc({
      numPages: 100,
      getPage: vi.fn().mockImplementation((p: number) => Promise.resolve(pages[p])),
    })

    const result = await buildFontTOC(doc, () => false)
    const byTitle = Object.fromEntries(result.map(e => [e.title, e.level]))
    // Sizes 24 and 18 are both >= splitSize(18) → level 1
    expect(byTitle["Big Chapter"]).toBe(1)
    expect(byTitle["Another Chapter"]).toBe(1)
    expect(byTitle["Medium Section"]).toBe(1)
    // Size 14 < splitSize(18) → level 2
    expect(byTitle["Small Sub-section"]).toBe(2)
    expect(byTitle["Another Sub-section"]).toBe(2)
  })
})
