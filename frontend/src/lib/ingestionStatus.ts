import type { IngestionStatus } from "@/lib/ingestionApi"

const STAGE_LABELS: Record<string, string> = {
  downloading: "Downloading audio",
  parsing: "Parsing document",
  transcribing: "Transcribing",
  correcting: "Checking transcript terms",
  classifying: "Classifying content",
  chunking: "Chunking text",
  embedding: "Generating embeddings",
  indexing: "Building keyword index",
  summarizing: "Summarising sections",
  entity_extract: "Extracting entities",
  complete: "Complete",
  error: "Failed",
}

export function stageLabel(stage: string, progressPct: number, stagePct?: number | null): string {
  const label = STAGE_LABELS[stage]
  return label ? withStagePct(label, stagePct) : `Processing (${progressPct}%)`
}

/** A long stage (download, transcription) says how far it has got. */
export function withStagePct(label: string, stagePct: number | null | undefined): string {
  return stagePct == null ? label : `${label} (${stagePct}%)`
}

/**
 * The user-facing pause state, or null when nothing is being held back.
 *
 * Indexing yields to a question in flight (backend admission control), and a
 * pause nobody announced reads as a hang — I-10. Only shown while the document
 * is still being processed: a finished or failed ingestion has nothing to pause.
 */
export function pauseNote(status: Pick<IngestionStatus, "stage" | "paused_for_interaction">):
  | string
  | null {
  if (status.stage === "complete" || status.stage === "error") return null
  return status.paused_for_interaction
    ? "Paused while you're asking — indexing resumes when your answer is done."
    : null
}
