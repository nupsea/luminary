// StrugglingPanel -- list of flashcards the learner has hit "Again"
// repeatedly in the last 14 days. Each row offers a "Re-read source"
// jump back to the originating section in the document reader.

import { useQuery } from "@tanstack/react-query"
import { AlertCircle, BookOpen } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { API_BASE } from "@/lib/config"
import { useAppStore } from "@/store"

import type { StrugglingCard } from "./types"

async function fetchStrugglingCards(documentId: string): Promise<StrugglingCard[]> {
  const res = await fetch(
    `${API_BASE}/study/struggling?document_id=${encodeURIComponent(documentId)}`,
  )
  if (!res.ok) throw new Error("Failed to load struggling cards")
  return res.json() as Promise<StrugglingCard[]>
}

interface StrugglingPanelProps {
  documentId: string
}

export function StrugglingPanel({ documentId }: StrugglingPanelProps) {
  const navigate = useNavigate()
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)

  const { data: cards = [], isLoading, isError } = useQuery<StrugglingCard[], Error>({
    queryKey: ["struggling", documentId],
    queryFn: () => fetchStrugglingCards(documentId),
    enabled: !!documentId,
  })

  function handleReread(card: StrugglingCard) {
    if (!card.document_id) return
    setActiveDocument(card.document_id)
    if (card.source_section_id) {
      void navigate(`/?section_id=${encodeURIComponent(card.source_section_id)}`)
    } else {
      void navigate("/")
    }
  }

  if (!documentId) return null

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold text-foreground">Struggling Cards</h2>

      {isLoading ? (
        <div className="flex flex-col gap-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-md bg-muted" />
          ))}
        </div>
      ) : isError ? (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle size={14} />
          Failed to load struggling cards. Please try refreshing.
        </div>
      ) : cards.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No struggling cards in the last 14 days.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {cards.map((card) => (
            <div
              key={card.flashcard_id}
              className="flex items-start justify-between gap-3 rounded-md border border-border bg-card px-4 py-3"
            >
              <div className="flex flex-col gap-1 flex-1 min-w-0">
                <p className="truncate text-sm text-foreground">{card.question}</p>
                <span className="inline-flex w-fit items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                  {card.again_count}x Again
                </span>
              </div>
              {card.source_section_id && (
                <button
                  onClick={() => handleReread(card)}
                  className="flex-shrink-0 flex items-center gap-1.5 rounded border border-border px-3 py-1 text-xs text-foreground hover:bg-accent"
                >
                  <BookOpen size={12} />
                  Re-read source
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
