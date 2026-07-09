import type {
  CompletionContext,
  CompletionResult,
} from "@codemirror/autocomplete"
import type { EditorView } from "@codemirror/view"

export interface NoteLinkCandidate {
  id: string
  preview: string
}

export interface NoteLinkCompletionConfig {
  fetchCandidates: (query: string) => Promise<NoteLinkCandidate[]>
  /** Fired after the marker is inserted; creates the typed link server-side. */
  onPick?: (targetNoteId: string) => void
  /** The note being edited -- excluded from candidates. */
  excludeId?: () => string | null
}

// Matches an unclosed [[query on the current line, anchored at the cursor.
export const NOTE_LINK_TRIGGER = /\[\[([^\]\n]*)$/

// Marker labels live inside [[id|label]], so strip the delimiter characters.
export function linkLabel(preview: string): string {
  const line = preview.split("\n").find((l) => l.trim()) ?? ""
  const clean = line
    .replace(/^#+\s*/, "")
    .replace(/[`*_>[\]|]/g, "")
    .trim()
  return (clean.length > 60 ? clean.slice(0, 60).trimEnd() + "..." : clean) || "Untitled note"
}

export function noteLinkCompletionSource(getConfig: () => NoteLinkCompletionConfig | undefined) {
  return async (ctx: CompletionContext): Promise<CompletionResult | null> => {
    const config = getConfig()
    if (!config) return null
    const match = ctx.matchBefore(NOTE_LINK_TRIGGER)
    if (!match) return null
    const query = match.text.slice(2)
    let candidates: NoteLinkCandidate[]
    try {
      candidates = await config.fetchCandidates(query)
    } catch {
      return null
    }
    const exclude = config.excludeId?.() ?? null
    const options = candidates
      .filter((c) => c.id !== exclude)
      .map((c) => {
        const label = linkLabel(c.preview)
        return {
          label,
          type: "text",
          apply: (view: EditorView, _completion: unknown, from: number, to: number) => {
            const marker = `[[${c.id}|${label}]]`
            view.dispatch({
              changes: { from, to, insert: marker },
              selection: { anchor: from + marker.length },
            })
            config.onPick?.(c.id)
          },
        }
      })
    if (options.length === 0) return null
    // Server-side filtered; CM's own fuzzy filter would fight the backend.
    return { from: match.from, options, filter: false }
  }
}
