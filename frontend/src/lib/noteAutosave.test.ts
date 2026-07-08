import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  createNoteAutosaver,
  EMPTY_DRAFT,
  type AutosaveStatus,
  type NoteDraft,
} from "./noteAutosave"
import type { Note } from "./notesApi"

const makeNote = (id: string, content: string) => ({ id, content }) as unknown as Note

const draft = (content: string, rest: Partial<NoteDraft> = {}): NoteDraft => ({
  content,
  title: "",
  tags: [],
  sourceDocIds: [],
  ...rest,
})

function setup(overrides: { debounceMs?: number } = {}) {
  const statuses: AutosaveStatus[] = []
  const created: Note[] = []
  const create = vi.fn(async (d: NoteDraft) => makeNote("new-1", d.content))
  const patch = vi.fn(async (id: string, d: NoteDraft) => makeNote(id, d.content))
  const autosaver = createNoteAutosaver({
    create,
    patch,
    debounceMs: overrides.debounceMs ?? 1000,
    onStatus: (s) => statuses.push(s),
    onCreated: (n) => created.push(n),
  })
  return { autosaver, create, patch, statuses, created }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe("createNoteAutosaver", () => {
  it("debounces and creates a draft on first real content", async () => {
    const { autosaver, create, statuses, created } = setup()
    autosaver.bind(null, EMPTY_DRAFT)
    autosaver.update(draft("h"))
    await vi.advanceTimersByTimeAsync(999)
    expect(create).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(create).toHaveBeenCalledTimes(1)
    expect(create.mock.calls[0][0].content).toBe("h")
    expect(created).toHaveLength(1)
    expect(autosaver.noteId()).toBe("new-1")
    expect(statuses).toEqual(["idle", "saving", "saved"])
  })

  it("flips to patch mode after the create", async () => {
    const { autosaver, create, patch } = setup()
    autosaver.bind(null, EMPTY_DRAFT)
    autosaver.update(draft("hello"))
    await vi.advanceTimersByTimeAsync(1000)
    autosaver.update(draft("hello world"))
    await vi.advanceTimersByTimeAsync(1000)
    expect(create).toHaveBeenCalledTimes(1)
    expect(patch).toHaveBeenCalledTimes(1)
    expect(patch.mock.calls[0][0]).toBe("new-1")
    expect(patch.mock.calls[0][1].content).toBe("hello world")
  })

  it("never creates for whitespace-only content", async () => {
    const { autosaver, create } = setup()
    autosaver.bind(null, EMPTY_DRAFT)
    autosaver.update(draft("   \n  "))
    await vi.advanceTimersByTimeAsync(5000)
    expect(create).not.toHaveBeenCalled()
  })

  it("never patches an existing note down to empty", async () => {
    const { autosaver, patch } = setup()
    autosaver.bind("id-1", draft("original"))
    autosaver.update(draft(""))
    await vi.advanceTimersByTimeAsync(5000)
    expect(patch).not.toHaveBeenCalled()
  })

  it("serializes a slow create with a follow-up edit: latest wins, one create", async () => {
    const { patch, statuses } = setup()
    let resolveCreate!: (n: Note) => void
    const slowCreate = vi.fn(
      () => new Promise<Note>((resolve) => (resolveCreate = resolve)),
    )
    const a = createNoteAutosaver({
      create: slowCreate,
      patch,
      debounceMs: 1000,
      onStatus: (s) => statuses.push(s),
    })
    a.bind(null, EMPTY_DRAFT)
    a.update(draft("a"))
    await vi.advanceTimersByTimeAsync(1000)
    expect(slowCreate).toHaveBeenCalledTimes(1)
    a.update(draft("ab"))
    await vi.advanceTimersByTimeAsync(1000)
    resolveCreate(makeNote("new-1", "a"))
    await vi.runAllTimersAsync()
    expect(slowCreate).toHaveBeenCalledTimes(1)
    expect(patch).toHaveBeenCalledTimes(1)
    expect(patch.mock.calls[0][0]).toBe("new-1")
    expect(patch.mock.calls[0][1].content).toBe("ab")
  })

  it("flush saves immediately without waiting for the debounce", async () => {
    const { autosaver, patch } = setup()
    autosaver.bind("id-1", draft("original"))
    autosaver.update(draft("edited"))
    const saved = await autosaver.flush()
    expect(patch).toHaveBeenCalledTimes(1)
    expect(saved?.content).toBe("edited")
    await vi.advanceTimersByTimeAsync(5000)
    expect(patch).toHaveBeenCalledTimes(1)
  })

  it("flush on a clean state is a no-op returning the last save", async () => {
    const { autosaver, create, patch } = setup()
    autosaver.bind("id-1", draft("original"))
    const saved = await autosaver.flush()
    expect(saved).toBeNull()
    expect(create).not.toHaveBeenCalled()
    expect(patch).not.toHaveBeenCalled()
  })

  it("reports error, keeps state dirty, and retries on next flush", async () => {
    const statuses: AutosaveStatus[] = []
    const patch = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockImplementation(async (id: string, d: NoteDraft) => makeNote(id, d.content))
    const a = createNoteAutosaver({
      create: async (d) => makeNote("new-1", d.content),
      patch,
      debounceMs: 1000,
      onStatus: (s) => statuses.push(s),
    })
    a.bind("id-1", draft("original"))
    a.update(draft("edited"))
    await expect(a.flush()).rejects.toThrow("boom")
    expect(statuses.at(-1)).toBe("error")
    const saved = await a.flush()
    expect(saved?.content).toBe("edited")
    expect(patch).toHaveBeenCalledTimes(2)
    expect(statuses.at(-1)).toBe("saved")
  })

  it("rebinding resets identity and baseline", async () => {
    const { autosaver, create, patch } = setup()
    autosaver.bind("id-1", draft("one"))
    autosaver.update(draft("one edited"))
    await vi.advanceTimersByTimeAsync(1000)
    expect(patch).toHaveBeenCalledTimes(1)
    autosaver.bind(null, EMPTY_DRAFT)
    expect(autosaver.noteId()).toBeNull()
    expect(autosaver.lastSaved()).toBeNull()
    autosaver.update(draft("two"))
    await vi.advanceTimersByTimeAsync(1000)
    expect(create).toHaveBeenCalledTimes(1)
    expect(create.mock.calls[0][0].content).toBe("two")
  })

  it("tag and source-doc changes alone trigger a save", async () => {
    const { autosaver, patch } = setup()
    autosaver.bind("id-1", draft("body"))
    autosaver.update(draft("body", { tags: ["ml"] }))
    await vi.advanceTimersByTimeAsync(1000)
    expect(patch).toHaveBeenCalledTimes(1)
    expect(patch.mock.calls[0][1].tags).toEqual(["ml"])
  })
})
