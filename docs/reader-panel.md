---
description: The reader's docked panel — faces, citations, the note composer, live markdown, the practice loop, and what make verify-dock fires. Read before touching components/reader, the docked chat or composer, or practice in the reader.
---

# The reader panel

**Nothing opens over the document.** The resizable right panel is the assistant: `Insights · Ask AI ·
Notes · Practice`, plus `Explain` while there is an explanation to read. Selection actions dock into
it and carry their citation.

`readerSurfaces.test.ts` holds the claim: no file under `components/reader/` may import a dialog,
sheet, drawer or alert-dialog primitive, or be named for one, and the reader must mount all five
faces. The document's delete confirmation is a popover and needs no exception.

- Every face stays mounted and hidden, and collapsing the panel hides it rather than unmounting. A
  layout change may not cost a streaming answer or an unsaved draft. One ref records where a
  transient face returns, so closing lands on whatever opened it.
- The selection bar carries Explain, Ask and four highlight swatches. A highlight is the whole of
  passage capture; it resolves to a section or page, not a `chunk_id`.
- The reader header carries no panel tab. A goal's Study button in `ChapterGoalsPanel` scopes
  Practice to that goal's section instead of leaving.
- Each face wears its feature's icon elsewhere (`Brain`, `MessageSquare`, `StickyNote`); Insights is
  `ScrollText`, because `Sparkles` is Chat's Creative toggle.

## Citations

`lib/citation/locus` picks one locus per source: a moment for a recording, a page for a paginated
document, otherwise the section. It returns null when the source has none, which is what stops a
chip claiming "p.0"; its tests carry a deliberately unresolvable ref that must format to nothing.

- `chunks.start_time` and `end_time` persist the transcript windows. **Recordings ingested before they
  existed carry no timings; only a re-ingest fills them.** `ChunkLocation` is a NamedTuple so a new
  field cannot shift its unpacking call sites.
- There is no `line` kind. The code chunker stores its start line in `chunks.page_number` with no
  flag, so a citation cannot tell a line from a page.
- A citation clicked in the docked conversation is answered beside it (`onCitationInDocument`).
  Routing to `/library?doc=` remounts the reader and loses the panel. A citation into a different
  document still routes.

## The docked conversation

`ChatConversation` holds the thread, composer and session list; `variant="docked"` drops the session
list, back button and `?q=` prefill, and `Chat.tsx` is the route around it.

**A conversation belongs to the surface holding it.** `chatThreads` is keyed `page` for Ask and
`doc:<id>` for a docked conversation. One global thread let the dock re-scope the Ask page, which had
to be fixed once already (`957b5be`). A docked conversation is pinned to its document with no scope
picker, which is why Ask stays on the nav rail for questions across the library. Preloaded questions
are addressed the same way (`preloadIsFor`), so an `autoSubmit` question cannot land in the wrong
thread.

## The note composer

`NoteComposer` holds the capture. `variant="sheet"` is for a page with no room beside it
(`QuickNoteComposer` wraps it); `variant="docked"` is the Notes face.

- A second selection appends into the open draft (`appendCapture`).
- Opening a note from the panel edits it in place, with autosave bound to that note. An existing note
  is never discarded for being emptied; only a new draft is.
- Expanding to the full note page sets `from` to `/library?doc=…&note=…`, so Back returns to the
  reader with the note open. A `from` with a query is a place, not a history step.

## Live markdown

`liveMarkdown` renders as it writes in `layout="editor"`, the only layout with no preview pane. It
hides inline markers on every line but the cursor's, and draws blocks (fenced code, tables, a lone
image, `$$` math) with `MarkdownRenderer`, so editor and preview cannot disagree. The full note page
turns it on when its preview toggle is off; it is reconfigured on the built view, not read at mount.

- **A click answers with the character under it.** Code maps the pointer through the rendering to an
  offset in the body; a table answers with the clicked cell. A block whose first and last lines are
  fences (```` ``` ````, `$$`) never hands the caret to a fence line. Landing on a fence is what
  produced ```` X```python ```` and collapsed every block below.
- A rendered block is one position to CodeMirror, so up and down put the caret on its first or last
  content line.
- A drawn diagram is the image plus its sidecar HTML comment, and the block spans both so the edit
  button can reach the scene (`NoteDiagramDialog`). Offsets it returns are block-relative.
- Three grammar traps: block decorations must come from a `StateField` (a `ViewPlugin` throws); `$$`
  blocks are found by scanning text, since the markdown grammar has no math; an HTML comment is
  `HTMLBlock`, `CommentBlock` or `Comment` depending on context, and all three must be hidden.

## Practice in the reader

Practice opens on the deck for what is being read (what is here, what is due), with `CardGenerator`
below it. `ExplanationPanel`, `PracticePanel` and `FeynmanPanel` are faces, not modals.

- **The answer is not rendered until the learner commits**: a three-point confidence prediction or a
  typed explanation. Hidden behind a class, it could be read ahead.
- Revealing moves the reading pane to the card's section. Only `GET /study/due` joins a section onto
  cards, so a resumed or non-due run resolves the locus through
  `GET /flashcards/{id}/source-context`. Otherwise the jump disappears on the second run of any deck.
- A run's mode is fixed at start (`RecallRunner` takes it as a prop), because
  `POST /study/teachback/async` rewrites its session's mode.
- **A teach-back is not graded by hand.** Scoring applies its own FSRS review, so the grade buttons
  appear on recall cards only; offering them on a scored card reviews it twice.
  `InlineTeachbackFeedback` shows all three rubric dimensions and says so when the best-effort rubric
  call comes back empty.
- **Retry in place, never delete and retry.** Deleting a session removes its teach-back rows and
  review events but leaves the card's FSRS state advanced, so it keeps the schedule move it appeared
  to undo.
- **Start starts; only the resume button resumes.** `prepareStudySession` adopts any open session,
  which is right on the Study page and wrong here. The deck names the most recent open run and
  resumes by id; a resume that lands on a different session is refused out loud.
- The runs on this document are the Study page's `SessionHistory`, in both modes. Emptying a deck
  removes the runs it emptied from both views (I-52).
- `sourceNote` speaks for the quote and `answerCheckNote` for the answer. Most cards are
  `grounding=verified, factuality=unchecked`, and one "found in this document" line beside an
  unverified answer reads as an endorsement.
- Calibration is scored once, in `recallFeedback.ts`, shared with the Study page.

## Dictation

`POST /audio/transcribe` hands a browser recording to the same `AudioTranscriber` that ingests audio.
It needs the `transcription` component, which the installer may not carry, so the mic reads a
`dictation` capability and is absent until it is installed. The macOS entitlements it needs are in
`desktop-bundle.md`.

## Nav

Six rail items: Home, Library, Notes, Study, Ask, Progress. `surfaceManifest.test.ts` pins them. Map
stays `full`; `blog` is `public`.

## `make verify-dock`

What no unit test sees, because all of it is mounted components sharing one store: asking about a
passage keeps the reader on it, the docked thread leaves the Ask page untouched, a note opens nothing
over the text, the recall loop withholds the answer until commit, a capture keeps its `section_id`
and words across a reload, and the progress header's numerator never exceeds a cap taken from
`GET /flashcards/{document_id}` (not the endpoint the header is built from). Each check was fired by
breaking what it guards. It needs a document with a card due, and it deletes what it creates.

Two arms are off by default, with the reason beside the flag in `frontend/scripts/verify-dock.mjs`:

| Flag | Off because |
|---|---|
| `LUMINARY_VERIFY_TEACHBACK=1` | scoring applies an FSRS review, and deleting the session does not undo card state |
| `LUMINARY_VERIFY_FEYNMAN=1` | `/feynman` has no delete, so every run leaves a session in the library |

The verdict check does not require a score: a local evaluation sometimes comes back unscored, and a
check that reddens on that hides a real regression.
