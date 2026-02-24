import { BookOpen, Code2, MessageSquare, ScrollText, StickyNote } from "lucide-react"
import type { ContentType, LearningStatus } from "./types"

export const CONTENT_TYPE_ICONS: Record<ContentType, React.ElementType> = {
  book: BookOpen,
  paper: ScrollText,
  conversation: MessageSquare,
  notes: StickyNote,
  code: Code2,
}

export const STATUS_LABELS: Record<LearningStatus, string> = {
  not_started: "Not started",
  summarized: "Summarized",
  flashcards_generated: "Flashcards",
  studied: "Studied",
}

export const STATUS_VARIANTS: Record<
  LearningStatus,
  "gray" | "blue" | "indigo" | "green"
> = {
  not_started: "gray",
  summarized: "blue",
  flashcards_generated: "indigo",
  studied: "green",
}

export function formatWordCount(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}K words`
  }
  return `${count} words`
}

export function relativeDate(isoStr: string): string {
  const date = new Date(isoStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return "Today"
  if (diffDays === 1) return "Yesterday"
  if (diffDays < 7) return `${diffDays} days ago`
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
  return `${Math.floor(diffDays / 30)}mo ago`
}
