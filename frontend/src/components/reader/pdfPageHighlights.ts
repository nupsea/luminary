/**
 * Highlights drawn over one rendered PDF page: saved annotations, search
 * matches and the cited passage, each located in the page's text layer.
 */

import type { AnnotationItem, SectionItem } from "./types"
import { findMatchIndices } from "./pdfSearchUtils"
import { clearOverlays, computeHighlightRects, renderOverlayDivs } from "./pdfHighlightOverlay"
import {
  CITATION_OVERLAY_ATTR,
  CITATION_OVERLAY_COLOR,
  findRunOffsets,
  longestPresentRun,
} from "@/lib/citation"

/**
 * Build span-offset parts from the text layer for highlight rect computation.
 * Reused by both annotation and search highlight functions.
 */
function buildTextParts(textLayerDiv: HTMLDivElement) {
  const spans = Array.from(textLayerDiv.querySelectorAll("span")) as HTMLSpanElement[]
  if (spans.length === 0) return null
  const parts: { span: HTMLSpanElement; start: number; end: number }[] = []
  let offset = 0
  for (let i = 0; i < spans.length; i++) {
    if (i > 0) offset += 1 // space separator (matches browser selection toString())
    const text = spans[i].textContent ?? ""
    parts.push({ span: spans[i], start: offset, end: offset + text.length })
    offset += text.length
  }
  const fullText = spans.map((s) => s.textContent ?? "").join(" ")
  return { spans, parts, fullText }
}

/**
 * Build a whitespace-stripped view of the text plus a map from each compact
 * index back to its offset in the original text.
 */
function buildWhitespaceMap(fullText: string): { compact: string; map: number[] } {
  let compact = ""
  const map: number[] = []
  for (let i = 0; i < fullText.length; i++) {
    if (!/\s/.test(fullText[i])) {
      compact += fullText[i]
      map.push(i)
    }
  }
  return { compact, map }
}

const PDF_HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "rgba(250, 204, 21, 0.4)",  // yellow-400
  green: "rgba(74, 222, 128, 0.4)",   // green-400
  blue: "rgba(96, 165, 250, 0.4)",    // blue-400
  pink: "rgba(244, 114, 182, 0.4)",   // pink-400
}

/** Apply annotation highlight overlays using absolutely-positioned divs. */
export function applyPdfHighlights(
  textLayerDiv: HTMLDivElement,
  overlayContainer: HTMLDivElement,
  annotations: AnnotationItem[],
  currentPage: number,
  sections: SectionItem[],
) {
  clearOverlays(overlayContainer, "data-pdf-highlight")

  if (annotations.length === 0) return

  // 1. Filter annotations for current page efficiently
  const sectionMap = new Map<string, SectionItem>()
  for (const s of sections) sectionMap.set(s.id, s)

  const pageAnnotations = annotations.filter((ann) => {
    if (ann.page_number != null) return ann.page_number === currentPage
    const sec = sectionMap.get(ann.section_id)
    if (sec) {
      const start = sec.page_start || 1
      const end = sec.page_end || start
      return currentPage >= start && currentPage <= end
    }
    return true
  })

  if (pageAnnotations.length === 0) return

  // Sort by start_offset so we find occurrences in document order.
  // This is critical for the "find next occurrence" strategy to work.
  const sortedAnnotations = [...pageAnnotations].sort((a, b) => (a.start_offset || 0) - (b.start_offset || 0))

  const textData = buildTextParts(textLayerDiv)
  if (!textData) return
  const { spans, parts, fullText } = textData

  const containerRect = overlayContainer.getBoundingClientRect()

  // Whitespace-insensitive view of the text layer, computed once. The text
  // layer joins spans with single spaces, but a selection captured via
  // selection.toString() may differ in spacing around bullets, line breaks,
  // and punctuation (e.g. "data. •" in the layer vs "data.•" in the
  // selection). Matching on whitespace-stripped text and mapping back to the
  // full offset tolerates those differences.
  const { compact: compactFull, map: compactMap } = buildWhitespaceMap(fullText)

  const usedFullOffsets = new Set<number>()
  const usedCompactOffsets = new Set<number>()

  for (const ann of sortedAnnotations) {
    const searchVal = ann.selected_text
    if (!searchVal) continue

    let idx = -1
    let matchEnd = -1
    let searchStart = 0

    // Fast path: next unused exact occurrence in the joined text.
    while (true) {
      idx = fullText.indexOf(searchVal, searchStart)
      if (idx < 0) break
      if (!usedFullOffsets.has(idx)) {
        usedFullOffsets.add(idx)
        break
      }
      searchStart = idx + 1
    }

    if (idx >= 0) {
      matchEnd = idx + searchVal.length
    } else {
      // Fallback: whitespace-insensitive next-occurrence search.
      const compactSearch = searchVal.replace(/\s+/g, "")
      if (!compactSearch) continue

      let cIdx = -1
      let cStart = 0
      while (true) {
        cIdx = compactFull.indexOf(compactSearch, cStart)
        if (cIdx < 0) break
        if (!usedCompactOffsets.has(cIdx)) {
          usedCompactOffsets.add(cIdx)
          break
        }
        cStart = cIdx + 1
      }

      if (cIdx < 0) continue

      idx = compactMap[cIdx]
      matchEnd = compactMap[cIdx + compactSearch.length - 1] + 1
    }

    const bgColor = PDF_HIGHLIGHT_COLORS[ann.color] ?? PDF_HIGHLIGHT_COLORS.yellow

    const rects = computeHighlightRects(spans, parts, idx, matchEnd, containerRect)
    renderOverlayDivs(overlayContainer, rects, bgColor, "data-pdf-highlight", ann.id)
  }
}

/** Apply search-match highlights as overlay divs. Returns the active match's mark, if drawn. */
export function applySearchHighlights(
  textLayerDiv: HTMLDivElement,
  overlayContainer: HTMLDivElement,
  query: string,
  activeMatchIndex: number,
): Element | null {
  clearOverlays(overlayContainer, "data-search-highlight")

  if (!query) return null

  const textData = buildTextParts(textLayerDiv)
  if (!textData) return null
  const { spans, parts, fullText } = textData

  const matchIndices = findMatchIndices(fullText, query)
  if (matchIndices.length === 0) return null

  const containerRect = overlayContainer.getBoundingClientRect()
  const queryLen = query.length

  for (let mi = 0; mi < matchIndices.length; mi++) {
    const matchStart = matchIndices[mi]
    const matchEnd = matchStart + queryLen
    const isActive = mi === activeMatchIndex

    const color = isActive ? "rgba(249, 115, 22, 0.6)" : "rgba(250, 204, 21, 0.4)"
    const rects = computeHighlightRects(spans, parts, matchStart, matchEnd, containerRect)
    renderOverlayDivs(overlayContainer, rects, color, "data-search-highlight", undefined, isActive)
  }

  return overlayContainer.querySelector("[data-active-search-match]")
}

/**
 * Draw the cited passage on the page, and say whether it was found.
 *
 * The PDF renders the source itself, so a citation belongs on the page rather
 * than on the extracted text beside it. The words are located in the text layer's
 * concatenated span text, which joins spans with single spaces -- the same
 * whitespace tolerance the prose view needs, for the same reason: the stored
 * chunk collapsed the source's own spacing.
 */
export function applyCitationHighlight(
  textLayerDiv: HTMLDivElement,
  overlayContainer: HTMLDivElement,
  words: string[],
): boolean {
  clearOverlays(overlayContainer, CITATION_OVERLAY_ATTR)
  if (words.length === 0) return false

  const textData = buildTextParts(textLayerDiv)
  if (!textData) return false
  const { spans, parts, fullText } = textData

  // Narrow first, then locate -- the same two steps the prose view takes, for the
  // same reason. A citation's words include material this page does not hold
  // contiguously (a section heading the chunk was stored with, a tail that runs
  // onto the next page), so demanding the whole sequence finds nothing even on the
  // right page.
  const run = longestPresentRun(words, fullText)
  if (run.length === 0) return false

  const at = findRunOffsets(fullText, run)
  if (!at) return false

  const rects = computeHighlightRects(
    spans, parts, at.start, at.end, overlayContainer.getBoundingClientRect(),
  )
  renderOverlayDivs(overlayContainer, rects, CITATION_OVERLAY_COLOR, CITATION_OVERLAY_ATTR)
  return rects.length > 0
}
