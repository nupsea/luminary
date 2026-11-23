import { useSyncExternalStore } from "react"

// A stream outlives the component that started it: leaving a document unmounts its
// docked chat while the answer is still arriving. So which thread has a turn in
// flight lives here, not in component state, and a remount can see it.
const inFlight = new Set<string>()
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function beginTurn(threadKey: string): void {
  inFlight.add(threadKey)
  emit()
}

export function endTurn(threadKey: string): void {
  inFlight.delete(threadKey)
  emit()
}

export function isTurnInFlight(threadKey: string): boolean {
  return inFlight.has(threadKey)
}

export function useTurnInFlight(threadKey: string): boolean {
  return useSyncExternalStore(subscribe, () => inFlight.has(threadKey))
}
