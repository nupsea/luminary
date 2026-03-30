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

// ---------------------------------------------------------------------------
// Tag tree search / filter (S190)
// ---------------------------------------------------------------------------

export interface FilteredTagTreeItem extends TagTreeItem {
  /** True if this node itself matches the search query */
  matched: boolean
  /** Filtered children (only matching subtrees) */
  children: FilteredTagTreeItem[]
}

/**
 * Filter a tag tree by substring match on display_name or id (case-insensitive).
 * Parent nodes with matching descendants are included but marked matched=false (dimmed).
 * Returns empty array if nothing matches.
 */
export function filterTagTree(
  tree: TagTreeItem[],
  query: string,
): FilteredTagTreeItem[] {
  if (!query) return tree.map((n) => markAll(n, true))
  const q = query.toLowerCase()
  const result: FilteredTagTreeItem[] = []
  for (const node of tree) {
    const filtered = filterNode(node, q)
    if (filtered) result.push(filtered)
  }
  return result
}

function filterNode(node: TagTreeItem, q: string): FilteredTagTreeItem | null {
  const selfMatch =
    node.display_name.toLowerCase().includes(q) ||
    node.id.toLowerCase().includes(q)
  const filteredChildren: FilteredTagTreeItem[] = []
  for (const child of node.children) {
    const fc = filterNode(child, q)
    if (fc) filteredChildren.push(fc)
  }
  if (!selfMatch && filteredChildren.length === 0) return null
  return { ...node, matched: selfMatch, children: filteredChildren }
}

function markAll(node: TagTreeItem, matched: boolean): FilteredTagTreeItem {
  return {
    ...node,
    matched,
    children: node.children.map((c) => markAll(c, matched)),
  }
}

/**
 * Split text into segments for highlighting a substring match.
 * Returns array of { text, highlight } segments.
 */
export function highlightMatch(
  text: string,
  query: string,
): Array<{ text: string; highlight: boolean }> {
  if (!query) return [{ text, highlight: false }]
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return [{ text, highlight: false }]
  const segments: Array<{ text: string; highlight: boolean }> = []
  if (idx > 0) segments.push({ text: text.slice(0, idx), highlight: false })
  segments.push({ text: text.slice(idx, idx + query.length), highlight: true })
  if (idx + query.length < text.length)
    segments.push({ text: text.slice(idx + query.length), highlight: false })
  return segments
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
