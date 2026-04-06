/**
 * Pure utility functions for collection tree operations.
 * Extracted into a separate file so they can be unit-tested in a Node environment
 * without pulling in React or the Zustand store.
 */

export interface CollectionTreeItem {
  id: string
  name: string
  color: string
  icon: string | null
  note_count: number
  children: CollectionTreeItem[]
}

/** Flatten a 2-level collection tree into a single array (parent then children). */
export function flattenCollectionTree(items: CollectionTreeItem[]): CollectionTreeItem[] {
  const result: CollectionTreeItem[] = []
  for (const item of items) {
    result.push(item)
    for (const child of item.children) {
      result.push(child)
    }
  }
  return result
}

/**
 * Build the fetch request parameters for adding a note to a collection.
 * Used by NoteEditorDialog checkbox (checked -> POST).
 */
export function buildAddNoteRequest(
  apiBase: string,
  collectionId: string,
  noteId: string,
): { url: string; method: string; body: string; headers: Record<string, string> } {
  return {
    url: `${apiBase}/collections/${collectionId}/notes`,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note_ids: [noteId] }),
  }
}

/**
 * Build the fetch request parameters for removing a note from a collection.
 * Used by NoteEditorDialog checkbox (unchecked -> DELETE).
 */
export function buildRemoveNoteRequest(
  apiBase: string,
  collectionId: string,
  noteId: string,
): { url: string; method: string } {
  return {
    url: `${apiBase}/collections/${collectionId}/notes/${noteId}`,
    method: "DELETE",
  }
}

/**
 * Count the number of displayable items in a tree fixture.
 * Mirrors what CollectionTree renders: top-level items + expanded children.
 * When all parents are expanded, total items = flattenCollectionTree(tree).length.
 */
export function countTreeItems(items: CollectionTreeItem[]): number {
  return flattenCollectionTree(items).length
}
