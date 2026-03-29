/**
 * PDF Table-of-Contents utilities.
 *
 * Extracted from PDFViewer.tsx so they can be unit-tested independently of the
 * React component and the pdfjs worker.
 */
import type { PDFDocumentProxy } from "pdfjs-dist"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A resolved PDF outline (bookmark) entry with a 1-based page number. */
export interface OutlineEntry {
  title: string
  /** 1-based page number; 0 means unresolved — shown as a static label. */
  page: number
  level: number
  children: OutlineEntry[]
}

// ---------------------------------------------------------------------------
// resolveDestPage
// ---------------------------------------------------------------------------

/**
 * Resolve a pdfjs outline item's destination to a 1-based page number.
 *
 * Handles all three real-world destination formats in pdfjs v4:
 *   - Named destination (string) → resolve via doc.getDestination()
 *   - Explicit dest array with RefProxy as dest[0] → doc.getPageIndex()
 *   - Explicit dest array with integer as dest[0] → use directly (0-based)
 *     (many PDF generators use integers; getPageIndex() would throw on them)
 *
 * Returns -1 when the destination cannot be resolved.
 */
export async function resolveDestPage(
  doc: PDFDocumentProxy,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rawDest: string | Array<unknown>,
): Promise<number> {
  const dest: Array<unknown> | null =
    typeof rawDest === "string" ? await doc.getDestination(rawDest) : rawDest
  if (!dest || !Array.isArray(dest) || dest.length === 0) return -1
  const ref = dest[0]
  if (typeof ref === "number") {
    return ref + 1 // 0-based integer index stored directly
  }
  if (ref !== null && typeof ref === "object") {
    // RefProxy: { num, gen } — standard pdfjs page reference
    return (await doc.getPageIndex(ref as Parameters<typeof doc.getPageIndex>[0])) + 1
  }
  return -1 // null ref = "current page" with no useful page number
}

// ---------------------------------------------------------------------------
// resolveOutline
// ---------------------------------------------------------------------------

/**
 * Recursively resolve a pdfjs outline tree into OutlineEntry objects.
 *
 * Every item is kept — even those whose destination cannot be resolved.
 * Unresolvable items get page = 0 and render as non-navigable labels.
 * "More sections is always better": the caller never drops entries.
 */
export async function resolveOutline(
  doc: PDFDocumentProxy,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  items: Array<any>,
  level: number,
): Promise<OutlineEntry[]> {
  const results: OutlineEntry[] = []
  for (const item of items) {
    let page = 0 // 0 = unresolved
    try {
      if (item.dest) {
        const resolved = await resolveDestPage(doc, item.dest)
        if (resolved >= 1) page = resolved
      }
    } catch {
      // non-fatal — keep entry with page = 0
    }
    const children = item.items?.length
      ? await resolveOutline(doc, item.items, level + 1)
      : []
    results.push({ title: item.title, page, level, children })
  }
  return results
}

// ---------------------------------------------------------------------------
// flattenOutline
// ---------------------------------------------------------------------------

/** Flatten a nested outline tree into a single array, preserving level. */
export function flattenOutline(entries: OutlineEntry[]): OutlineEntry[] {
  const flat: OutlineEntry[] = []
  for (const e of entries) {
    flat.push(e)
    if (e.children.length) flat.push(...flattenOutline(e.children))
  }
  return flat
}

// ---------------------------------------------------------------------------
// buildFontTOC
// ---------------------------------------------------------------------------

/**
 * Build a TOC by scanning PDF text content for heading-sized lines.
 *
 * Three-stage filter pipeline (all heuristics, no hardcoded sizes):
 *
 * 1. Early-zone duplicate removal — printed TOC pages list chapter titles that
 *    also appear later as real headings. Any candidate in the first ~12% of pages
 *    (min 5, max 30) whose normalised text also exists on a later page is a TOC
 *    listing and is dropped. Unique early-page headings (preface, etc.) survive.
 *
 * 2. Density filter — a page with ≥3 heading-sized items is a list/TOC page;
 *    all its candidates are removed. Real content pages have at most 1–2 headings.
 *
 * 3. Gap filter — any remaining heading whose nearest neighbour is < 2 pages away
 *    is still noise (running headers, decorative repeat text, etc.) and dropped.
 *
 * Level assignment: body size = median of all items; threshold = body × 1.15.
 * Sizes are bucketed to 0.5 pt; the largest gap between adjacent buckets splits
 * level 1 (large) from level 2 (everything else).
 */
export async function buildFontTOC(
  doc: PDFDocumentProxy,
  isCancelled: () => boolean,
): Promise<OutlineEntry[]> {
  const totalPages = doc.numPages
  const rawItems: { page: number; text: string; size: number }[] = []

  for (let p = 1; p <= totalPages; p++) {
    if (isCancelled()) return []
    const page = await doc.getPage(p)
    const content = await page.getTextContent()
    for (const item of content.items) {
      if (!("str" in item) || !item.str.trim()) continue
      const size = item.height > 0 ? item.height : Math.abs(item.transform[3] ?? 0)
      rawItems.push({ page: p, text: item.str.trim(), size })
    }
  }

  if (rawItems.length === 0) return []

  const positiveSizes = rawItems.map(i => i.size).filter(s => s > 0)
  if (positiveSizes.length === 0) return []

  const sortedSizes = [...positiveSizes].sort((a, b) => a - b)
  const bodyMedian = sortedSizes[Math.floor(sortedSizes.length / 2)]
  const headingThreshold = bodyMedian * 1.15

  const candidates = rawItems.filter(
    i => i.size >= headingThreshold && i.text.length >= 2 && i.text.length < 120,
  )
  if (candidates.length === 0) return []

  // Stage 1: early-zone duplicate removal
  const earlyZone = Math.min(30, Math.max(5, Math.ceil(totalPages * 0.12)))
  const normalise = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim()
  const textsAfterEarly = new Set(
    candidates.filter(c => c.page > earlyZone).map(c => normalise(c.text)),
  )
  const stage1 = candidates.filter(
    c => c.page > earlyZone || !textsAfterEarly.has(normalise(c.text)),
  )

  // Stage 2: density filter
  const pageCount = new Map<number, number>()
  for (const c of stage1) pageCount.set(c.page, (pageCount.get(c.page) ?? 0) + 1)
  const stage2 = stage1.filter(c => (pageCount.get(c.page) ?? 0) < 3)

  // Stage 3: gap filter
  const stage3 = stage2.filter((item, i) => {
    const prev = i > 0 ? item.page - stage2[i - 1].page : Infinity
    const next = i < stage2.length - 1 ? stage2[i + 1].page - item.page : Infinity
    return Math.min(prev, next) >= 2
  })

  if (stage3.length === 0) return []

  // Level assignment
  const sizeSet = [...new Set(stage3.map(i => Math.round(i.size * 2) / 2))].sort((a, b) => b - a)
  let splitSize = sizeSet[0]
  if (sizeSet.length >= 2) {
    let maxGap = 0
    for (let i = 0; i < sizeSet.length - 1; i++) {
      const gap = sizeSet[i] - sizeSet[i + 1]
      if (gap > maxGap) { maxGap = gap; splitSize = sizeSet[i + 1] }
    }
  }

  return stage3.map(item => ({
    title: item.text,
    page: item.page,
    level: item.size >= splitSize ? 1 : 2,
    children: [],
  }))
}

// ---------------------------------------------------------------------------
// shouldUseOutline
// ---------------------------------------------------------------------------

/**
 * Decide whether to render pdfOutline instead of backend sections.
 *
 * Rules:
 * - Never switch when the outline is empty.
 * - If no backend sections exist, always prefer the outline (font-based or native).
 * - If backend sections exist, only prefer the outline when it is at least as
 *   detailed — "more sections is always better", so never replace a richer view
 *   with a sparser one.
 */
export function shouldUseOutline(outlineLength: number, sectionsLength: number): boolean {
  if (outlineLength === 0) return false
  if (sectionsLength === 0) return true
  return outlineLength >= sectionsLength
}
