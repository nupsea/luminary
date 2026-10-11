// What a per-surface model choice reaches, and what it leaves alone. Stated next
// to the selector because a pinned model is otherwise indistinguishable from the
// Settings default until an answer comes back from the wrong engine.

import { shortModelLabel } from "@/lib/chatSettingsUtils"

export type ModelSurface = "chat" | "study" | "practice" | "blog"

const AFFECTS: Record<ModelSurface, string> = {
  // Ask stores the choice on the conversation, so it outlives a reload.
  chat: "Answers in this conversation, including after you reopen it.",
  study: "Cards generated on this page, until you leave it.",
  practice: "Cards generated in this panel, until you close it.",
  blog: "This refinement only.",
}

const LEAVES: Record<ModelSurface, string> = {
  chat: "Settings, other conversations, Study and Practice, or the summaries and tags written in the background.",
  study: "Settings, Ask, Practice, or the summaries and tags written in the background.",
  practice: "Settings, Ask, Study, or the summaries and tags written in the background.",
  blog: "Settings, Ask, Study and Practice, or the summaries and tags written in the background.",
}

export interface ModelScopeCopy {
  status: string
  affects: string
  leaves: string
}

export function modelScopeCopy(
  surface: ModelSurface,
  override: string,
  effectiveDefault: string,
): ModelScopeCopy {
  const status = override
    ? `Pinned to ${shortModelLabel(override)}. Choose Auto to follow Settings again.`
    : `Auto follows Settings, which uses ${shortModelLabel(effectiveDefault)} now.`
  return { status, affects: AFFECTS[surface], leaves: LEAVES[surface] }
}
