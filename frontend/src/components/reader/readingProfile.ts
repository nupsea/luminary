/**
 * Reading profiles, keyed off both axes the pipeline records.
 * See docs/universal-reader.md.
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
  /** "opener" ignores depth; "hierarchy" sizes by `level`. */
  headingStyle: "opener" | "hierarchy"
  /** Split the body into speaker turns and label each one. */
  speakerTurns: boolean
}

const SPECS: Record<ReadingProfile, ProfileSpec> = {
  // 66ch: middle of the 50-75 readable range.
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
  // Wider: code and tables suffer more from wrapping than prose does.
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
  // Unrelated entries; the rule is all that separates them.
  reference: {
    measureCh: 66,
    family: "font-sans",
    dividers: true,
    headingStyle: "hierarchy",
    speakerTurns: false,
  },
}

const BY_KIND: Record<string, ReadingProfile> = {
  book: "prose",
  paper: "paper",
  code: "technical",
  notes: "reference",
  conversation: "dialogue",
  audio: "dialogue",
  video: "dialogue",
}

/**
 * Only layouts the kind cannot express. Values present on both axes must
 * not override, or the finer kind would lose to the coarser layout.
 */
const BY_STRUCTURE_TYPE: Record<string, ReadingProfile> = {
  chat: "dialogue",
  script: "script",
}

export function readingProfile(doc: {
  kind?: string | null
  form?: string | null
  structure_type?: string | null
}): ReadingProfile {
  const structural = BY_STRUCTURE_TYPE[doc.structure_type ?? ""]
  if (structural) return structural
  // A technical article reads at article width; manuals and textbooks get the wider measure.
  if (doc.kind === "technical") return doc.form === "article" ? "article" : "technical"
  return BY_KIND[doc.kind ?? ""] ?? "article"
}

export function profileSpec(profile: ReadingProfile): ProfileSpec {
  return SPECS[profile]
}

export interface ResolvedLayout extends ProfileSpec {
  lineHeight: number
  fontScale: number
  tinted: boolean
}

/** Fold reader preferences over profile defaults; "auto" keeps tracking. */
export function resolveReadingLayout(
  spec: ProfileSpec,
  prefs: {
    family: "auto" | "serif" | "sans"
    fontScale: number
    lineHeight: number
    measureCh: number | null
    tint: "auto" | "paper"
  },
): ResolvedLayout {
  const family =
    prefs.family === "auto"
      ? spec.family
      : prefs.family === "serif"
        ? "font-serif prose-headings:font-serif"
        : "font-sans prose-headings:font-sans"
  return {
    ...spec,
    family,
    measureCh: prefs.measureCh ?? spec.measureCh,
    lineHeight: prefs.lineHeight,
    fontScale: prefs.fontScale,
    tinted: prefs.tint === "paper",
  }
}
