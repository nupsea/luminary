// Reading GET /settings/llm/routing, and the one sentence that summarises it.
//
// Separate from the component so the summary can be unit-tested: Vitest runs in
// the node environment here, so pure logic lives in lib/ and components stay
// untested by convention.

import { apiGet } from "@/lib/apiClient"
import { providerSetup } from "@/lib/engineOffer"
import type { components } from "@/types/api"

export type RoutingResponse = components["schemas"]["RoutingResponse"]
export type WorkRoutingItem = components["schemas"]["WorkRoutingItem"]

/** An unsaved choice to report routes for; the backend resolves it without saving. */
export interface RoutingPreview {
  mode: string
  provider?: string
  model?: string
}

export function fetchRouting(preview?: RoutingPreview): Promise<RoutingResponse> {
  return apiGet<RoutingResponse>("/settings/llm/routing", preview ? { ...preview } : undefined)
}

/**
 * The preview to show, or undefined when the form matches what is saved.
 *
 * Provider and model only count in Hybrid and Cloud, and an empty model is
 * left out so the backend applies the provider's default, as saving would.
 */
export function pendingRouting(
  saved: { mode: string; provider: string; model: string } | undefined,
  form: { mode: string; provider: string; model: string },
): RoutingPreview | undefined {
  if (!saved) return undefined
  const usesProvider = form.mode !== "private"
  const changed =
    form.mode !== saved.mode ||
    (usesProvider && (form.provider !== saved.provider || form.model !== saved.model))
  if (!changed) return undefined
  if (!usesProvider) return { mode: form.mode }
  return { mode: form.mode, provider: form.provider, ...(form.model ? { model: form.model } : {}) }
}

/**
 * The sentence under the routing table.
 *
 * Derived from the rows rather than written per mode. Three hardcoded sentences
 * used to sit here, and one of them was wrong for a year -- it told the reader
 * flashcards stayed local in hybrid mode while card generation took the
 * interactive route. A summary computed from the rows cannot drift from them.
 */
export function egressSummary(data: RoutingResponse): string {
  const notRun = data.work.filter((w) => w.refused_reason)
  const notRunLine =
    notRun.length > 0
      ? ` Not run on this machine: ${joinLabels(notRun.map((w) => w.label.toLowerCase()))}.`
      : ""
  const leaving = data.work.filter((w) => !w.on_device)
  if (leaving.length === 0) {
    return `Nothing leaves this machine.${notRunLine}`
  }
  const provider = data.provider
    ? (providerSetup(data.provider)?.label ?? data.provider)
    : "your provider"
  // Enrichment is the one routable row that sends document text rather than a
  // question: in Cloud mode a summary is written from a section, not a retrieval.
  const sendsSections = leaving.some((w) => w.id === "enrichment")
  const withQuestions = leaving.filter((w) => w.id !== "enrichment")
  const parts = [`Only ${joinLabels(leaving.map((w) => w.label.toLowerCase()))} reach ${provider}.`]
  if (withQuestions.length > 0) {
    parts.push(
      `${capitalise(joinLabels(withQuestions.map((w) => w.label.toLowerCase())))} send your question plus the passages retrieved for it.`,
    )
  }
  if (sendsSections) {
    parts.push("Summaries, tags and titles send sections of your documents.")
  }
  parts.push("Your library, its index and your learner record stay on this machine.")
  return `${parts.join(" ")}${notRunLine}`
}

export function joinLabels(labels: string[]): string {
  if (labels.length <= 1) return labels[0] ?? ""
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
