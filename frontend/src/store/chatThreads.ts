// One conversation per surface.
//
// The Ask page and a conversation docked in a reader are different conversations
// about different things: the dock asks about the document in front of it. The
// thread, its scope and its persisted session were single global values, so
// mounting a second conversation anywhere would have re-scoped the first -- the
// defect 957b5be fixed once already, where a library question went out scoped to
// a PDF forty seconds into ingestion.

export interface ChatThread {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  messages: any[]
  scope: "single" | "all"
  selectedDocId: string | null
  sessionId: string | null
  error: string | null
}

/** The Ask page's conversation. */
export const PAGE_THREAD = "page"

/** A conversation docked in a reader, one per document. */
export function docThreadKey(documentId: string): string {
  return `doc:${documentId}`
}

/**
 * Frozen and shared: a component selecting a thread that does not exist yet must
 * get the same object every render, or the selector returns a new literal each
 * time and the subscription re-renders forever.
 */
export const EMPTY_THREAD: ChatThread = Object.freeze({
  messages: Object.freeze([]) as unknown as unknown[],
  scope: "all",
  selectedDocId: null,
  sessionId: null,
  error: null,
})

export function threadOf(
  threads: Record<string, ChatThread>,
  key: string,
): ChatThread {
  return threads[key] ?? EMPTY_THREAD
}

export function withThread(
  threads: Record<string, ChatThread>,
  key: string,
  patch: Partial<ChatThread>,
): Record<string, ChatThread> {
  return { ...threads, [key]: { ...threadOf(threads, key), ...patch } }
}

/**
 * v1 stored one conversation as four flat keys. Folding them into the page
 * thread is what keeps an open conversation open across the upgrade.
 */
export function migrateChatThreads(persisted: Record<string, unknown>): Record<string, unknown> {
  if (persisted["chatThreads"]) return persisted
  const page: ChatThread = {
    messages: Array.isArray(persisted["chatMessages"]) ? (persisted["chatMessages"] as unknown[]) : [],
    scope: persisted["chatScope"] === "single" ? "single" : "all",
    selectedDocId: (persisted["chatSelectedDocId"] as string | null) ?? null,
    sessionId: (persisted["activeChatSessionId"] as string | null) ?? null,
    error: null,
  }
  const next: Record<string, unknown> = { ...persisted, chatThreads: { [PAGE_THREAD]: page } }
  delete next["chatMessages"]
  delete next["chatScope"]
  delete next["chatSelectedDocId"]
  delete next["activeChatSessionId"]
  return next
}

/** What a preloaded question is addressed to. */
export interface ChatPreload {
  text: string
  documentId: string | null
  autoSubmit?: boolean
  /** Which conversation should pick it up. Absent means the Ask page. */
  threadKey?: string
}

/**
 * Whether this conversation should consume the preload.
 *
 * Addressed, not broadcast: with a conversation docked in the reader and the Ask
 * page both mounted, an unaddressed preload would be claimed by whichever
 * happened to render -- the question would land in the wrong conversation, and
 * with `autoSubmit` it would send itself there.
 */
export function preloadIsFor(
  preload: ChatPreload | null | undefined,
  threadKey: string,
): boolean {
  if (!preload) return false
  return (preload.threadKey ?? PAGE_THREAD) === threadKey
}
