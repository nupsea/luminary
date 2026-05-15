/**
 * ClozeCard — fill-in-the-blank flashcard renderer
 *
 * Parses cloze_text with {{term}} markers and reveals blanks progressively
 * left-to-right. Once all blanks are revealed, FSRS rating buttons appear.
 * Falls back to Q&A rendering if cloze_text is null or has no valid blanks.
 */

import { useState } from "react"

type Rating = "again" | "hard" | "good" | "easy"

interface FlashcardCard {
  id: string
  question: string
  answer: string
  source_excerpt: string
  due_date: string | null
  section_id: string | null
  flashcard_type: string | null
  cloze_text: string | null
}

interface ClozeCardProps {
  card: FlashcardCard
  onRate: (rating: Rating) => Promise<void>
  isRating: boolean
}

type ClozeSegment =
  | { type: "text"; content: string }
  | { type: "blank"; term: string }

/** Parse cloze_text into alternating text and blank segments. Exported for testing. */
export function parseClozeSegments(clozeText: string): ClozeSegment[] {
  const parts = clozeText.split(/(\{\{.+?\}\})/g)
  return parts.map((part) => {
    const match = /^\{\{(.+?)\}\}$/.exec(part)
    return match
      ? { type: "blank" as const, term: match[1] }
      : { type: "text" as const, content: part }
  })
}

const RATINGS: { label: string; value: Rating; className: string }[] = [
  {
    label: "Again",
    value: "again",
    className: "bg-red-100 text-red-700 border-red-200 hover:bg-red-200",
  },
  {
    label: "Hard",
    value: "hard",
    className: "bg-orange-100 text-orange-700 border-orange-200 hover:bg-orange-200",
  },
  {
    label: "Good",
    value: "good",
    className: "bg-green-100 text-green-700 border-green-200 hover:bg-green-200",
  },
  {
    label: "Easy",
    value: "easy",
    className: "bg-blue-100 text-blue-700 border-blue-200 hover:bg-blue-200",
  },
]

export function ClozeCard({ card, onRate, isRating }: ClozeCardProps) {
  const [revealedCount, setRevealedCount] = useState(0)

  // Validate cloze_text has at least one blank
  const segments = card.cloze_text ? parseClozeSegments(card.cloze_text) : []
  const blanks = segments.filter((s) => s.type === "blank")
  const totalBlanks = blanks.length

  // Fallback to Q&A display if cloze_text is null or has no blanks
  if (totalBlanks === 0) {
    return (
      <div className="w-full rounded-xl border border-border bg-card p-6 shadow-sm">
        <div className="mb-4 text-sm font-medium text-muted-foreground">Question</div>
        <p className="text-lg text-foreground">{card.question}</p>
        <div className="mt-6 border-t border-border pt-4">
          <div className="mb-2 text-sm font-medium text-muted-foreground">Answer</div>
          <p className="text-base text-foreground">{card.answer}</p>
        </div>
      </div>
    )
  }

  const allRevealed = revealedCount >= totalBlanks
  let blankIndex = 0

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="w-full rounded-xl border border-border bg-card p-6 shadow-sm">
        <div className="mb-3 flex items-center gap-2">
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
            Cloze
          </span>
          <span className="text-xs text-muted-foreground">
            {revealedCount}/{totalBlanks} revealed
          </span>
        </div>
        <p className="text-lg leading-relaxed text-foreground">
          {segments.map((seg, i) => {
            if (seg.type === "text") {
              return <span key={i}>{seg.content}</span>
            }
            // blank segment
            const thisBlankIndex = blankIndex++
            const isRevealed = thisBlankIndex < revealedCount
            return (
              <span
                key={i}
                className={`inline-block min-w-[4rem] rounded border-b-2 px-1 text-center transition-all duration-300 ${
                  isRevealed
                    ? "border-primary font-bold text-primary"
                    : "border-foreground text-muted-foreground"
                }`}
              >
                {isRevealed ? seg.term : "?"}
              </span>
            )
          })}
        </p>
      </div>

      {!allRevealed ? (
        <button
          onClick={() => setRevealedCount((c) => c + 1)}
          className="rounded bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Reveal next blank
        </button>
      ) : (
        <div className="flex gap-3">
          {RATINGS.map(({ label, value, className }) => (
            <button
              key={value}
              onClick={() => void onRate(value)}
              disabled={isRating}
              className={`rounded border px-5 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 ${className}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
