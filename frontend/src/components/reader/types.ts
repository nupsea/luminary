// API shapes sourced from generated `src/types/api.ts` (audit #15).
// AnnotationItem's `color` is intersected to keep the strict literal
// union the highlight-color UI uses (the generated schema has it as
// plain `string`).

import type { components } from "@/types/api"

export type SectionItem = components["schemas"]["SectionItem"]
export type DocumentDetail = components["schemas"]["DocumentDetail"]
export type ChunkItem = components["schemas"]["ChunkItem"]
export type SectionContentItem = components["schemas"]["SectionContentItem"]

export type AnnotationColor = "yellow" | "green" | "blue" | "pink"

export type AnnotationItem = Omit<
  components["schemas"]["AnnotationResponse"],
  "color"
> & {
  color: AnnotationColor
}

export type SummaryMode = "one_sentence" | "executive" | "detailed" | "conversation"

export interface SummaryTabDef {
  mode: SummaryMode
  label: string
}

export const SUMMARY_TABS: SummaryTabDef[] = [
  { mode: "executive", label: "Key Points" },
  { mode: "detailed", label: "Detailed" },
]

export const CONVERSATION_TAB: SummaryTabDef = {
  mode: "conversation",
  label: "Meeting Notes",
}
