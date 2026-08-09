/**
 * Split transcript text into speaker turns so the dialogue profile can label
 * each one. Markdown alone renders the exchange as a single block.
 */

export interface SpeakerTurn {
  speaker: string
  text: string
}

// Mirrors the `chat_standard` signature in backend universal_parser.py.
const TURN_RE = /^([A-Z][\w .'-]{0,30}):[ \t]+(.*)$/

/**
 * Returns null when the text is not a transcript, so the caller renders it as
 * ordinary markdown. A single leading line without a speaker (a title, a
 * participant roster) is kept as a turn with no speaker rather than dropped.
 */
export function parseSpeakerTurns(text: string): SpeakerTurn[] | null {
  const lines = text.split("\n")
  const turns: SpeakerTurn[] = []
  let matched = 0

  for (const line of lines) {
    const m = TURN_RE.exec(line.trim())
    if (m) {
      matched++
      turns.push({ speaker: m[1].trim(), text: m[2].trim() })
      continue
    }
    if (!line.trim()) continue
    if (turns.length === 0) {
      turns.push({ speaker: "", text: line.trim() })
      continue
    }
    // A wrapped continuation of the turn above.
    const last = turns[turns.length - 1]
    last.text = last.text ? `${last.text}\n${line.trim()}` : line.trim()
  }

  // Two turns is the floor for something to be a dialogue at all; below that a
  // stray "Note: ..." line would restyle an entire prose section.
  if (matched < 2) return null
  return demoteLeadingMetadata(turns)
}

/**
 * Strip speaker labels off the document's own header lines, which share a
 * turn's shape. A real speaker recurs, so a label occurring once before anyone
 * has spoken twice is metadata. Recurrence rather than a word list keeps this
 * language-agnostic; it engages only once some speaker does recur.
 */
function demoteLeadingMetadata(turns: SpeakerTurn[]): SpeakerTurn[] {
  const counts = new Map<string, number>()
  for (const t of turns) {
    if (t.speaker) counts.set(t.speaker, (counts.get(t.speaker) ?? 0) + 1)
  }
  const recurs = (speaker: string) => (counts.get(speaker) ?? 0) > 1
  if (![...counts.keys()].some(recurs)) return turns

  const firstRecurring = turns.findIndex((t) => t.speaker && recurs(t.speaker))
  return turns.map((turn, i) => {
    // Past the first recurring speaker the dialogue has begun, and a one-turn
    // participant there is a person, not a header.
    if (!turn.speaker || i > firstRecurring || recurs(turn.speaker)) return turn
    return { speaker: "", text: `${turn.speaker}: ${turn.text}` }
  })
}
