/**
 * Pure utility functions for hierarchical tag operations.
 * Used by TagTree and TagAutocomplete components.
 * No React/store imports -- safe for Vitest node environment.
 */

export interface TagTreeItem {
  id: string
  display_name: string
  parent_tag: string | null
  note_count: number
  children: TagTreeItem[]
}

export interface AutocompleteResult {
  id: string
  display_name: string
  parent_tag: string | null
  note_count: number
}

/**
 * Count total items that would be rendered in a fully expanded tag tree.
 * Top-level items + all children.
 */
export function countTagTreeItems(tree: TagTreeItem[]): number {
  let count = 0
  for (const item of tree) {
    count += 1 + countTagTreeItems(item.children)
  }
  return count
}

/**
 * Flatten a tag tree to a depth-first ordered list (parent before children).
 */
export function flattenTagTree(tree: TagTreeItem[]): TagTreeItem[] {
  const result: TagTreeItem[] = []
  for (const item of tree) {
    result.push(item)
    result.push(...flattenTagTree(item.children))
  }
  return result
}

/**
 * Parse a tag slug and return { root, rest | null }.
 * 'programming/python/3' -> { root: 'programming', rest: '/python/3' }
 * 'programming'           -> { root: 'programming', rest: null }
 */
export function parseTagBreadcrumb(tag: string): { root: string; rest: string | null } {
  const slashIdx = tag.indexOf("/")
  if (slashIdx === -1) return { root: tag, rest: null }
  return { root: tag.slice(0, slashIdx), rest: tag.slice(slashIdx) }
}

/**
 * Build the URL for POST /tags/merge.
 */
export function buildMergeRequest(
  apiBase: string,
  sourceTagId: string,
  targetTagId: string,
): { url: string; method: string; body: string; headers: Record<string, string> } {
  return {
    url: `${apiBase}/tags/merge`,
    method: "POST",
    body: JSON.stringify({ source_tag_id: sourceTagId, target_tag_id: targetTagId }),
    headers: { "Content-Type": "application/json" },
  }
}

/**
 * Build the URL for GET /tags/autocomplete?q=.
 */
export function buildAutocompleteUrl(apiBase: string, q: string): string {
  return `${apiBase}/tags/autocomplete?q=${encodeURIComponent(q)}`
}

/**
 * Filter autocomplete results for merge combobox:
 * exclude the source tag and filter by query substring.
 */
export function filterMergeOptions(
  tags: AutocompleteResult[],
  sourceTagId: string,
  query: string,
  limit = 10,
): AutocompleteResult[] {
  return tags
    .filter(
      (t) =>
        t.id !== sourceTagId &&
        (query === "" ||
          t.id.toLowerCase().includes(query.toLowerCase()) ||
          t.display_name.toLowerCase().includes(query.toLowerCase())),
    )
    .slice(0, limit)
}
