import type { DocumentKind } from "./types"

/** A chip for one document kind. */
export interface TypeChip {
  id: DocumentKind
  label: string
}

export interface LibraryFacets {
  kinds: Record<string, number>
  formats: Record<string, number>
  total: number
  favorite_count?: number
}

/** How many documents a chip stands for, over the whole library. */
export function chipCount(chip: TypeChip, facets: LibraryFacets | undefined): number {
  return facets?.kinds[chip.id] ?? 0
}

export function toggleChip(chip: TypeChip, selected: Set<DocumentKind>): Set<DocumentKind> {
  const next = new Set(selected)
  if (next.has(chip.id)) next.delete(chip.id)
  else next.add(chip.id)
  return next
}

/** The chips worth offering: the ones with documents behind them.
 *
 *  Counts come from the server over the whole library; a page of results cannot
 *  answer this, because a filter's matches can sit on page two.
 */
export function visibleChips(chips: TypeChip[], facets: LibraryFacets | undefined) {
  return chips
    .map((chip) => ({ chip, count: chipCount(chip, facets) }))
    .filter(({ count }) => count > 0)
}
