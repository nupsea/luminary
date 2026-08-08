/**
 * Reading profiles: how a document should be laid out for reading.
 *
 * Keyed off both axes the pipeline records (see docs/universal-reader.md).
 * `content_type` says what the document is and how it chunks; `structure_type`
 * says how it is laid out. Neither is sufficient alone -- a recorded technical
 * talk is `content_type: "audio"` and `structure_type: "chat"`, and only the
 * second one knows to render it as dialogue.
 */

export type ReadingProfile =
  | "prose"
  | "article"
  | "paper"
  | "technical"
  | "dialogue"
  | "script"
  | "reference"

export interface ProfileSpec {
  /** Line length, in characters of the profile's own typeface. */
  measureCh: number
  /** Tailwind family class, merged over MarkdownRenderer's default sans. */
  family: string
  /** Rule between consecutive sections. */
  dividers: boolean
  /**
   * "opener" gives a chapter title air above and below and does not scale with
   * depth -- a novel has one heading level and it marks a pause, not a rank.
   * "hierarchy" sizes the heading by `level` so nesting is visible.
   */
  headingStyle: "opener" | "hierarchy"
  /** Split the body into speaker turns and label each one. */
  speakerTurns: boolean
}

const SPECS: Record<ReadingProfile, ProfileSpec> = {
  // 66ch is the middle of the 50-75 research range and the classic ideal.
  prose: {
    measureCh: 66,
    family: "font-serif prose-headings:font-serif",
    dividers: false,
    headingStyle: "opener",
    speakerTurns: false,
  },
  article: {
    measureCh: 72,
    family: "font-sans",
    dividers: false,
    headingStyle: "hierarchy",
    speakerTurns: false,
  },
  paper: {
    measureCh: 72,
    family: "font-sans",
    dividers: false,
    headingStyle: "hierarchy",
    speakerTurns: false,
  },
  // Wider: code and tables read worse when wrapped than prose does when long.
  technical: {
    measureCh: 78,
    family: "font-sans",
    dividers: false,
    headingStyle: "hierarchy",
    speakerTurns: false,
  },
  dialogue: {
    measureCh: 66,
    family: "font-sans",
    dividers: true,
    headingStyle: "hierarchy",
    speakerTurns: true,
  },
  script: {
    measureCh: 66,
    family: "font-sans",
    dividers: false,
    headingStyle: "opener",
    speakerTurns: false,
  },
  // Clippings and note dumps are lists of unrelated entries; the rule between
  // them is the only thing separating one excerpt from the next.
  reference: {
    measureCh: 66,
    family: "font-sans",
    dividers: true,
    headingStyle: "hierarchy",
    speakerTurns: false,
  },
}

const BY_CONTENT_TYPE: Record<string, ReadingProfile> = {
  book: "prose",
  epub: "prose",
  paper: "paper",
  tech_book: "technical",
  tech_article: "article",
  code: "technical",
  notes: "article",
  conversation: "dialogue",
  audio: "dialogue",
  video: "dialogue",
  kindle_clippings: "reference",
}

/**
 * `structure_type` overrides only where it is strictly more specific than
 * anything `content_type` can express. "chat" and "script" are layouts with no
 * content_type equivalent; "book" and "paper" duplicate one and must not
 * override it, or a technical book laid out in numbered sections would lose its
 * wider measure to the prose profile.
 */
const BY_STRUCTURE_TYPE: Record<string, ReadingProfile> = {
  chat: "dialogue",
  script: "script",
}

export function readingProfile(doc: {
  content_type?: string | null
  structure_type?: string | null
}): ReadingProfile {
  const structural = BY_STRUCTURE_TYPE[doc.structure_type ?? ""]
  if (structural) return structural
  return BY_CONTENT_TYPE[doc.content_type ?? ""] ?? "article"
}

export function profileSpec(profile: ReadingProfile): ProfileSpec {
  return SPECS[profile]
}
