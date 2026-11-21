import { describe, expect, it } from "vitest"

import {
  EMPTY_THREAD,
  PAGE_THREAD,
  docThreadKey,
  migrateChatThreads,
  preloadIsFor,
  settleThreads,
  settleUnanswered,
  threadOf,
  UNANSWERED,
  withThread,
} from "./chatThreads"

describe("thread keys", () => {
  it("keeps a document's conversation apart from the page's", () => {
    expect(docThreadKey("abc")).not.toBe(PAGE_THREAD)
    expect(docThreadKey("abc")).not.toBe(docThreadKey("def"))
  })
})

describe("threadOf", () => {
  it("hands back one shared object for a conversation that has not started", () => {
    // A new literal per render would make the store subscription fire forever.
    expect(threadOf({}, PAGE_THREAD)).toBe(threadOf({}, docThreadKey("x")))
  })

  it("returns the stored thread when there is one", () => {
    const thread = { ...EMPTY_THREAD, sessionId: "s1" }
    expect(threadOf({ [PAGE_THREAD]: thread }, PAGE_THREAD)).toBe(thread)
  })
})

describe("withThread", () => {
  it("leaves every other conversation untouched", () => {
    const page = { ...EMPTY_THREAD, sessionId: "page-session" }
    const next = withThread({ [PAGE_THREAD]: page }, docThreadKey("d1"), { scope: "single" })
    expect(next[PAGE_THREAD]).toBe(page)
    expect(next[docThreadKey("d1")].scope).toBe("single")
  })

  it("does not mutate what it was given", () => {
    const threads = { [PAGE_THREAD]: { ...EMPTY_THREAD } }
    withThread(threads, PAGE_THREAD, { error: "boom" })
    expect(threads[PAGE_THREAD].error).toBeNull()
  })

  it("patches, so an unnamed field survives", () => {
    const start = withThread({}, PAGE_THREAD, { sessionId: "s1", scope: "single" })
    const next = withThread(start, PAGE_THREAD, { error: "boom" })
    expect(next[PAGE_THREAD]).toEqual({ ...EMPTY_THREAD, sessionId: "s1", scope: "single", error: "boom" })
  })
})

describe("migrateChatThreads", () => {
  it("carries an open conversation across the upgrade", () => {
    const migrated = migrateChatThreads({
      chatMessages: [{ id: "m1" }],
      chatScope: "single",
      chatSelectedDocId: "doc-7",
      activeChatSessionId: "sess-3",
      notesView: "list",
    })
    const threads = migrated["chatThreads"] as Record<string, unknown>
    expect(threads[PAGE_THREAD]).toEqual({
      messages: [{ id: "m1" }],
      scope: "single",
      selectedDocId: "doc-7",
      sessionId: "sess-3",
      error: null,
    })
    // The flat keys go, so a later read cannot resurrect a stale copy.
    expect(migrated).not.toHaveProperty("chatMessages")
    expect(migrated["notesView"]).toBe("list")
  })

  it("leaves already-migrated state alone", () => {
    const already = { chatThreads: { [PAGE_THREAD]: { ...EMPTY_THREAD, sessionId: "s" } } }
    expect(migrateChatThreads(already)).toBe(already)
  })

  it("survives a first run with nothing persisted", () => {
    const threads = migrateChatThreads({})["chatThreads"] as Record<string, unknown>
    expect(threads[PAGE_THREAD]).toEqual({ ...EMPTY_THREAD, messages: [] })
  })
})

describe("preloadIsFor", () => {
  const docKey = docThreadKey("d1")

  it("sends an unaddressed preload to the Ask page", () => {
    // Every dispatch site that predates docking leaves the key off.
    const preload = { text: "explain this", documentId: "d1" }
    expect(preloadIsFor(preload, PAGE_THREAD)).toBe(true)
    expect(preloadIsFor(preload, docKey)).toBe(false)
  })

  it("sends an addressed preload only to the conversation named", () => {
    const preload = { text: "explain this", documentId: "d1", threadKey: docKey }
    expect(preloadIsFor(preload, docKey)).toBe(true)
    expect(preloadIsFor(preload, PAGE_THREAD)).toBe(false)
    expect(preloadIsFor(preload, docThreadKey("d2"))).toBe(false)
  })

  it("is false when there is nothing waiting", () => {
    expect(preloadIsFor(null, PAGE_THREAD)).toBe(false)
    expect(preloadIsFor(undefined, docKey)).toBe(false)
  })
})

describe("settleUnanswered", () => {
  const user = (text: string) => ({ id: `u-${text}`, role: "user" as const, text })
  const answer = (text: string) => ({ id: `a-${text}`, role: "assistant" as const, text })

  it("adds a retryable failed turn after a question the session holds no answer for", () => {
    const settled = settleUnanswered([user("q1"), answer("a1"), user("q2")])
    expect(settled).toHaveLength(4)
    expect(settled[3]).toMatchObject({ role: "assistant", error: UNANSWERED, failedQuestion: "q2" })
  })

  it("turns a stream left open into a failed turn carrying its own question", () => {
    const open = { id: "a2", role: "assistant" as const, text: "partial", isStreaming: true }
    const settled = settleUnanswered([user("q1"), answer("a1"), user("q2"), open])
    expect(settled).toHaveLength(4)
    expect(settled[3]).toMatchObject({ isStreaming: false, text: "", error: UNANSWERED, failedQuestion: "q2" })
  })

  it("leaves an answered conversation as it is", () => {
    const messages = [user("q1"), answer("a1")]
    expect(settleUnanswered(messages)).toBe(messages)
    expect(settleUnanswered([])).toEqual([])
  })

  it("settles every stored thread as the store is read back", () => {
    const open = { id: "a1", role: "assistant", text: "", isStreaming: true }
    const threads = settleThreads({ [docThreadKey("d")]: { ...EMPTY_THREAD, messages: [user("q1"), open] } })
    expect(threads[docThreadKey("d")].messages[1]).toMatchObject({ isStreaming: false, failedQuestion: "q1" })
  })
})
