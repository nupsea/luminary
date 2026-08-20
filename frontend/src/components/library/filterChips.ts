import type { ContentType } from "./types"

/** A chip and the content types it stands for.
 *
 *  `types` is a list because Technical is one choice at upload and two stored
 *  values after classification.
 */
export interface TypeChip {
  id: string
  label: string
  types: ContentType[]
}

export interface LibraryFacets {
  content_types: Record<string, number>
  formats: Record<string, number>
  total: number
}

/** How many documents a chip stands for, over the whole library. */
export function chipCount(chip: TypeChip, facets: LibraryFacets | undefined): number {
  const counts = facets?.content_types ?? {}
  return chip.types.reduce((n, t) => n + (counts[t] ?? 0), 0)
}

/** A chip standing for two stored types is on only when both are selected. */
export function chipIsActive(chip: TypeChip, selected: Set<ContentType>): boolean {
  return chip.types.every((t) => selected.has(t))
}

/** Toggling a chip moves every type it stands for, together. */
export function toggleChip(chip: TypeChip, selected: Set<ContentType>): Set<ContentType> {
  const next = new Set(selected)
  const on = chipIsActive(chip, selected)
  for (const t of chip.types) {
    if (on) next.delete(t)
    else next.add(t)
  }
  return next
}

/** The chips worth offering: the ones with documents behind them.
 *
 *  The library carried ten chips and five could match nothing in any library --
 *  `code` is not in the backend's ContentType union, `epub` is a format, and
 *  `kindle_clippings` and `notes` name things no document here is. Counts come
 *  from the server over the whole library; a page of results cannot answer this,
 *  because a filter's matches can sit on page two.
 */
export function visibleChips(chips: TypeChip[], facets: LibraryFacets | undefined) {
  return chips
    .map((chip) => ({ chip, count: chipCount(chip, facets) }))
    .filter(({ count }) => count > 0)
}
