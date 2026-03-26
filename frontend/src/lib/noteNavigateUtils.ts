/**
 * Pure utilities for dispatching luminary:navigate events to the Notes tab
 * with a tag filter applied.
 *
 * Split per "Vitest node env + DOM events pure utility pattern":
 *  - buildTagNavigateDetail: pure function, testable in node env
 *  - dispatchTagNavigate: side-effectful wrapper, not tested in node env
 */

export function buildTagNavigateDetail(tagPath: string): { tab: string; filter: { tag: string } } {
  return { tab: "notes", filter: { tag: tagPath } }
}

export function dispatchTagNavigate(tagPath: string): void {
  window.dispatchEvent(
    new CustomEvent("luminary:navigate", { detail: buildTagNavigateDetail(tagPath) }),
  )
}
