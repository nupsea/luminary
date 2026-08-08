/**
 * Split transcript text into speaker turns.
 *
 * Transcripts reach the reader as "Speaker: utterance" lines in one body (I-30
 * keeps utterances out of headings). Markdown treats a single newline as a soft
 * break, so the whole exchange renders as one wall of text with the names
 * buried inside it. Splitting here lets the dialogue profile set each name as a
 * label beside its turn.
 */

export interface SpeakerTurn {
  speaker: string
  text: string
}

// Mirrors the `chat_standard` signature in backend universal_parser.py. A
// speaker name is short and starts a line; anything longer is prose that
// happens to contain a colon.
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
 * Strip speaker labels off the document's own header lines.
 *
 * A transcript usually opens with "Transcript: ...", "Date: ...",
 * "Participants: ..." -- same shape as a turn, so they were rendered as three
 * people who each spoke once. A real speaker takes more than one turn, so a
 * label that occurs once before anybody has spoken twice is metadata, not a
 * name. Deciding it by recurrence rather than by a list of known header words
 * keeps this working for transcripts in any language.
 *
 * Engages only once some speaker actually recurs. In a short exchange where
 * three people each speak once, every label is a person and demoting them all
 * would strip the section of its speakers.
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
