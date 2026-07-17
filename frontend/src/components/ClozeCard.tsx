/**
 * ClozeCard — fill-in-the-blank flashcard renderer
 *
 * Parses cloze_text with {{term}} markers and reveals blanks progressively
 * left-to-right. Once all blanks are revealed, FSRS rating buttons appear.
 * Falls back to Q&A rendering if cloze_text is null or has no valid blanks.
 */

import { useEffect, useRef, useState } from "react"
import { isButtonActivation, isTypingTarget } from "@/lib/keyboard"

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
    className: "bg-red-100 text-red-700 border-red-200 hover:bg-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900 dark:hover:bg-red-900/50",
  },
  {
    label: "Hard",
    value: "hard",
    className: "bg-orange-100 text-orange-700 border-orange-200 hover:bg-orange-200 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-900 dark:hover:bg-orange-900/50",
  },
  {
    label: "Good",
    value: "good",
    className: "bg-green-100 text-green-700 border-green-200 hover:bg-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-900 dark:hover:bg-green-900/50",
  },
  {
    label: "Easy",
    value: "easy",
    className: "bg-blue-100 text-blue-700 border-blue-200 hover:bg-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900 dark:hover:bg-blue-900/50",
  },
]

export function ClozeCard({ card, onRate, isRating }: ClozeCardProps) {
  const [revealedCount, setRevealedCount] = useState(0)
  // Latch: the outgoing card keeps its window listener alive during the exit
  // animation, so without it a fast second keypress would re-rate this card.
  const ratedRef = useRef(false)

  // Validate cloze_text has at least one blank
  const segments = card.cloze_text ? parseClozeSegments(card.cloze_text) : []
  const blanks = segments.filter((s) => s.type === "blank")
  const totalBlanks = blanks.length
  const allRevealed = revealedCount >= totalBlanks

  function rateOnce(value: Rating) {
    if (ratedRef.current) return
    ratedRef.current = true
    onRate(value).catch(() => {
      ratedRef.current = false
    })
  }

  // Keyboard: Space/Enter reveals the next blank; 1-4 grade once all blanks
  // are revealed. Esc is handled by the session-level listener.
  useEffect(() => {
    if (totalBlanks === 0) return
    function onKeyDown(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return
      // A focused button owns Enter/Space -- let native activation click it.
      if (isButtonActivation(e)) return
      if (!allRevealed) {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault()
          setRevealedCount((c) => c + 1)
        }
        return
      }
      if (isRating) return
      const grade: Record<string, Rating> = { "1": "again", "2": "hard", "3": "good", "4": "easy" }
      const rating = grade[e.key]
      if (rating) {
        e.preventDefault()
        rateOnce(rating)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allRevealed, totalBlanks, isRating])

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
        <div className="flex flex-col items-center gap-2">
          <button
            onClick={() => setRevealedCount((c) => c + 1)}
            data-kbnav
            className="rounded bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Reveal next blank
          </button>
          <p className="text-[11px] text-muted-foreground">Space to reveal · Esc to end</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <div className="flex gap-3">
            {RATINGS.map(({ label, value, className }, i) => (
              <button
                key={value}
                onClick={() => rateOnce(value)}
                disabled={isRating}
                data-kbnav
                aria-label={`${label} (press ${i + 1})`}
                className={`flex items-center gap-1.5 rounded border px-5 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ${className}`}
              >
                <span className="opacity-50">{i + 1}</span>
                {label}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground">1–4 to rate · Esc to end</p>
        </div>
      )}
    </div>
  )
}
