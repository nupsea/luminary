import { useCallback, useEffect, useRef, useState } from "react"
import { createNote, patchNote, type Note } from "@/lib/notesApi"

export interface NoteDraft {
  content: string
  title: string
  tags: string[]
  sourceDocIds: string[]
}

export type AutosaveStatus = "idle" | "saving" | "saved" | "error"

export interface NoteAutosaverOptions {
  create: (draft: NoteDraft) => Promise<Note>
  patch: (id: string, draft: NoteDraft) => Promise<Note>
  debounceMs?: number
  onStatus?: (status: AutosaveStatus) => void
  onCreated?: (note: Note) => void
  onSaved?: (note: Note) => void
}

export const EMPTY_DRAFT: NoteDraft = { content: "", title: "", tags: [], sourceDocIds: [] }

const serialize = (d: NoteDraft) => JSON.stringify([d.content, d.title, d.tags, d.sourceDocIds])

export function createNoteAutosaver(opts: NoteAutosaverOptions) {
  const debounceMs = opts.debounceMs ?? 1000
  let id: string | null = null
  let draft: NoteDraft = EMPTY_DRAFT
  let savedSnapshot = serialize(draft)
  let last: Note | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  // Saves run through a promise chain so a slow create can never race the
  // patch that follows it -- latest state always wins, no overlapping writes.
  let chain: Promise<unknown> = Promise.resolve()

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const isDirty = () => serialize(draft) !== savedSnapshot

  function bind(noteId: string | null, baseline: NoteDraft) {
    clearTimer()
    id = noteId
    draft = baseline
    savedSnapshot = serialize(baseline)
    last = null
    opts.onStatus?.("idle")
  }

  function update(next: NoteDraft) {
    draft = next
    clearTimer()
    if (!isDirty()) return
    // Empty bodies are never persisted: no draft row is created until real
    // content exists, and an existing note keeps its last saved body. The
    // finalize path (close/Done) decides what happens to empties.
    if (!next.content.trim()) return
    timer = setTimeout(() => {
      save().catch(() => {})
    }, debounceMs)
  }

  function save(): Promise<Note | null> {
    clearTimer()
    const run = chain.then(async () => {
      if (!isDirty()) return last
      const snapshot: NoteDraft = {
        content: draft.content,
        title: draft.title,
        tags: [...draft.tags],
        sourceDocIds: [...draft.sourceDocIds],
      }
      if (!snapshot.content.trim()) return last
      opts.onStatus?.("saving")
      const creating = id === null
      const saved = creating ? await opts.create(snapshot) : await opts.patch(id!, snapshot)
      id = saved.id
      savedSnapshot = serialize(snapshot)
      last = saved
      if (creating) opts.onCreated?.(saved)
      opts.onSaved?.(saved)
      if (!isDirty()) opts.onStatus?.("saved")
      return saved
    })
    chain = run.catch(() => {})
    return run.catch((err: unknown) => {
      opts.onStatus?.("error")
      throw err
    })
  }

  return {
    bind,
    update,
    flush: save,
    noteId: () => id,
    lastSaved: () => last,
  }
}

export type NoteAutosaver = ReturnType<typeof createNoteAutosaver>

export const NEW_NOTE_KEY = "__new__"

export interface UseNoteAutosaveOptions {
  /** Note id, NEW_NOTE_KEY for an unsaved composer, or null to suspend. */
  bindKey: string | null
  baseline: NoteDraft
  draft: NoteDraft
  enabled: boolean
  debounceMs?: number
  onCreated?: (note: Note) => void
  onSaved?: (note: Note) => void
}

export function useNoteAutosave(options: UseNoteAutosaveOptions) {
  const [status, setStatus] = useState<AutosaveStatus>("idle")
  const latest = useRef(options)
  latest.current = options

  const autosaverRef = useRef<NoteAutosaver | null>(null)
  if (autosaverRef.current === null) {
    autosaverRef.current = createNoteAutosaver({
      debounceMs: options.debounceMs,
      create: (d) =>
        createNote({
          content: d.content,
          tags: d.tags,
          title: d.title.trim() || undefined,
          document_id: d.sourceDocIds[0] || null,
          source_document_ids: d.sourceDocIds,
        }),
      patch: (noteId, d) =>
        patchNote(noteId, {
          content: d.content,
          tags: d.tags,
          title: d.title.trim(),
          source_document_ids: d.sourceDocIds,
        }),
      onStatus: setStatus,
      onCreated: (n) => latest.current.onCreated?.(n),
      onSaved: (n) => latest.current.onSaved?.(n),
    })
  }

  const { bindKey, enabled, draft } = options

  useEffect(() => {
    if (bindKey === null) return
    autosaverRef.current!.bind(
      bindKey === NEW_NOTE_KEY ? null : bindKey,
      latest.current.baseline,
    )
  }, [bindKey])

  useEffect(() => {
    if (!enabled) return
    autosaverRef.current!.update(draft)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, draft.content, draft.title, draft.tags, draft.sourceDocIds])

  // Safety net for unmount mid-edit (e.g. route change); normal closes flush
  // explicitly so they can react to failures.
  useEffect(() => {
    const a = autosaverRef.current!
    return () => {
      a.flush().catch(() => {})
    }
  }, [])

  const flush = useCallback(() => autosaverRef.current!.flush(), [])
  const savedNoteId = useCallback(() => autosaverRef.current!.noteId(), [])

  return { status, flush, savedNoteId }
}
