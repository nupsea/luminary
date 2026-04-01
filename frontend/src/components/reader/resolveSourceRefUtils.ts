/**
 * resolveSourceRefUtils -- pure helpers for resolving section IDs from DOM
 * nodes and PDF section arrays. Extracted from DocumentReader.tsx (S198)
 * for testability.
 */

import type { SectionItem } from "./types"

/**
 * Walk up the DOM from `startContainer` looking for the nearest ancestor
 * element with a `data-section-id` attribute. Uses `closest()` when
 * possible (Element nodes), falls back to manual parentNode walk for
 * Text/Comment nodes.
 *
 * Returns the section ID string, or undefined if none found.
 */
export function resolveFromDom(startContainer: Node): string | undefined {
  // If the node itself is an Element, try closest() first (fast path)
  if (startContainer instanceof Element) {
    const el = startContainer.closest("[data-section-id]")
    if (el) return (el as HTMLElement).dataset.sectionId
  }

  // Manual walk for Text nodes and other non-Element nodes
  let node: Node | null = startContainer
  while (node) {
    if (node instanceof HTMLElement && node.dataset.sectionId) {
      return node.dataset.sectionId
    }
    node = node.parentNode
  }

  return undefined
}

/**
 * PDF fallback: resolve the current page number to a section ID.
 *
 * Strategy:
 * 1. If any section has page_start > 0, find the section whose page range
 *    contains currentPage. If no exact match, use the last section that
 *    starts before currentPage.
 * 2. If all sections have page_start = 0 (parser couldn't map pages),
 *    use proportional index mapping: currentPage / totalPages * sectionCount.
 * 3. Ultimate fallback: return the first section's ID.
 */
export function resolvePdfFallback(
  sections: SectionItem[],
  currentPage: number,
  totalPages?: number,
): string | undefined {
  if (sections.length === 0) return undefined

  const hasPageNums = sections.some((s) => s.page_start > 0)

  if (hasPageNums) {
    // Find section whose page range contains the current page
    let sec = sections.find((s) => {
      const start = s.page_start
      const end = s.page_end || start
      return start > 0 && currentPage >= start && currentPage <= end
    })

    // If no exact match, find the last section that starts before current page
    if (!sec) {
      for (let i = sections.length - 1; i >= 0; i--) {
        if (sections[i].page_start > 0 && sections[i].page_start <= currentPage) {
          sec = sections[i]
          break
        }
      }
    }

    if (sec) return sec.id
  } else if (totalPages && totalPages > 0) {
    // Proportional index mapping when all page_start = 0
    const idx = Math.min(
      Math.floor((currentPage - 1) / totalPages * sections.length),
      sections.length - 1,
    )
    return sections[idx].id
  }

  // Ultimate fallback: first section
  return sections[0].id
}
