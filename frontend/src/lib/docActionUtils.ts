/**
 * S191: Pure utility functions for document action menu navigation.
 * Builds luminary:navigate event detail objects for each action.
 */

export type DocAction = "read" | "chat" | "study" | "notes" | "viz"

export interface DocActionDetail {
  tab: string
  documentId?: string
}

/**
 * Build the luminary:navigate event detail for a document action.
 * Pure function -- no DOM or store side effects.
 */
export function buildDocActionDetail(action: DocAction, documentId: string): DocActionDetail {
  switch (action) {
    case "read":
      return { tab: "learning", documentId }
    case "chat":
      return { tab: "chat", documentId }
    case "study":
      return { tab: "study", documentId }
    case "notes":
      return { tab: "notes", documentId }
    case "viz":
      return { tab: "viz", documentId }
  }
}

export const DOC_ACTIONS: { action: DocAction; label: string }[] = [
  { action: "read", label: "Read" },
  { action: "chat", label: "Chat about this" },
  { action: "study", label: "Study flashcards" },
  { action: "notes", label: "View notes" },
  { action: "viz", label: "View in graph" },
]
