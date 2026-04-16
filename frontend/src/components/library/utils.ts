import { 
  Book, 
  BookOpen, 
  Bookmark, 
  Code, 
  Cpu, 
  FileText, 
  MessageSquare, 
  Mic, 
  Newspaper, 
  StickyNote, 
  Youtube 
} from "lucide-react"
import type { ContentType } from "./types"

export { Youtube }

export const CONTENT_TYPE_ICONS: Record<ContentType, React.ElementType> = {
  book: Book,
  paper: FileText,
  conversation: MessageSquare,
  notes: StickyNote,
  code: Code,
  audio: Mic,
  epub: BookOpen,
  kindle_clippings: Bookmark,
  tech_book: Cpu,
  tech_article: Newspaper,
}

export function isYouTubeDoc(doc: { source_url?: string | null }): boolean {
  return !!(doc.source_url?.includes("youtube") || doc.source_url?.includes("youtu.be"))
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${Math.round(seconds)}s`
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

export function formatDate(isoStr: string): string {
  return new Date(isoStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
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
