// Reading GET /settings/llm/routing, and the one sentence that summarises it.
//
// Separate from the component so the summary can be unit-tested: Vitest runs in
// the node environment here, so pure logic lives in lib/ and components stay
// untested by convention.

import { apiGet } from "@/lib/apiClient"
import type { components } from "@/types/api"

export type RoutingResponse = components["schemas"]["RoutingResponse"]
export type WorkRoutingItem = components["schemas"]["WorkRoutingItem"]

export function fetchRouting(): Promise<RoutingResponse> {
  return apiGet<RoutingResponse>("/settings/llm/routing")
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
  const leaving = data.work.filter((w) => !w.on_device)
  if (leaving.length === 0) {
    return "Nothing leaves this machine. Every model above runs on your own hardware."
  }
  const labels = leaving.map((w) => w.label.toLowerCase())
  const list =
    labels.length === 1
      ? labels[0]
      : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`
  const provider = data.provider ?? "your provider"
  return `Only ${list} reach ${provider}, and only ever as your question plus the passages retrieved for it. Your library, its index and your learner record stay on this machine.`
}
