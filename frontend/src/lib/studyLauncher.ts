// Study Launcher scope + dispatch helper (docs/study-launcher.md).
// Every study entry point dispatches `luminary:launch-study` with a scope; App.tsx
// listens and opens the launcher pre-filled (mirrors the luminary:navigate bus, I-11).

export type StudyScopeType =
  | "daily"
  | "concept"
  | "collection"
  | "doc"
  | "note"
  | "tag"
  | "selection"
  | "chat"
  | "planWeek"

export interface StudyScope {
  type: StudyScopeType
  ref?: string
  // human label shown in the sheet header (e.g. the collection / concept name)
  label?: string
}

export const LAUNCH_STUDY_EVENT = "luminary:launch-study"

/** Open the Study Launcher pre-filled with a scope, from any surface. */
export function launchStudy(scope: StudyScope): void {
  window.dispatchEvent(new CustomEvent(LAUNCH_STUDY_EVENT, { detail: { scope } }))
}
