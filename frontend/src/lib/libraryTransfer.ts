import type { components } from "@/types/api"

type LibraryContents = components["schemas"]["LibraryContents"]

const EXPORT_NAME = /^luminary-([a-z0-9][a-z0-9_-]*)-\d{8}-\d{6}\.tar\.gz$/

/** The name an exported archive's library had, unless it was the default (which is taken). */
export function suggestedLibraryName(fileName: string): string {
  const match = EXPORT_NAME.exec(fileName)
  return match && match[1] !== "default" ? match[1] : ""
}

function count(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`
}

export function describeContents(c: LibraryContents): string {
  return [
    count(c.documents, "document", "documents"),
    count(c.flashcards, "card", "cards"),
    count(c.notes, "note", "notes"),
  ].join(", ")
}
