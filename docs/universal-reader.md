# Universal Reader

The Universal Reader (`frontend/src/components/reader/ReadView.tsx`, served by
`GET /sections/{document_id}/content`) renders every non-PDF document: novels,
tech blogs, papers, transcripts, scripts, notes. The PDF Reader
(`PDFViewer.tsx`) is a separate surface and is not covered here.

## The rule that governs everything else

**Retrieval chunks are for retrieval. The reader never reconstructs prose from
them.** See I-29 in `docs/invariants.md`.

Chunks are sized for the embedder, not the eye. They cut mid-sentence, they
overlap, and 90% of them contain no paragraph break at all — measured on
`frankenstein` + `the_odyssey`, 261 of 2,599 chunks. Joining them with `\n\n`
fabricates a paragraph break every few hundred characters, each landing
mid-clause, and duplicates text at every overlap seam.

## Reading text: `sections.body`

`sections.body` holds the section's original text, uncapped. It is the only
source the reader may use.

`sections.preview` is capped at 10,000 chars and feeds section lists, flashcard
context, and the Feynman summary cache. It is **not** reading text — a section
longer than the cap is silently truncated mid-sentence.

`GET /sections/{id}/content` returns `content_source` naming which tier served
each section:

| `content_source` | Meaning | Fidelity |
|---|---|---|
| `body` | `sections.body` | Original text |
| `preview` | `sections.preview`, under the cap | Original text |
| `chunks` | Retrieval chunks re-joined | Degraded — false paragraph breaks, overlap duplication |

`chunks` exists only for documents ingested before `body` was added. It is
surfaced rather than hidden so the UI can offer re-ingestion; it is not a
fallback the pipeline may rely on. Documents ingested before the `body` column
must be re-uploaded to read at full fidelity — there is no backfill, because the
original text is not recoverable from what was stored.

## Two axes describe a document

Neither field alone picks a layout, so both are stored:

| Field | Source | Values | Answers |
|---|---|---|---|
| `documents.content_type` | `_classify` in `workflows/ingestion_nodes/_shared.py` | `book`, `paper`, `tech_book`, `tech_article`, `conversation`, `code`, `notes`, `audio`, `video`, `kindle_clippings`, `epub` | What the document is about, and how it chunks |
| `documents.structure_type` | `UniversalParser` signature discovery and `BookParser`, persisted by `parse_node` | `book`, `paper`, `script`, `chat` | How it is laid out |

`content_type` knows a transcript is technical; `structure_type` knows it is
dialogue. `structure_type` is null when the parser that ran discovers no
structure (the PDF font heuristic, the paragraph-split fallback) or the document
predates the column — it is a refinement, never a prerequisite.

`BookParser` runs before `UniversalParser` for `.txt`, and every one of its
return paths fires only after chapter segmentation succeeded, so it reports
`book`. Without that, the field was null for most novels — `the_odyssey.txt`
included.

## Reading profiles

`readingProfile()` in `frontend/src/components/reader/readingProfile.ts` maps
the two axes onto a layout; `profileSpec()` returns what that layout does.

| Profile | Selected by | Measure | Family | Headings | Dividers |
|---|---|---|---|---|---|
| `prose` | `book`, `epub` | 66ch | Serif | Opener | None |
| `article` | `tech_article`, `notes`, unknown | 72ch | Sans | Hierarchy | None |
| `paper` | `paper` | 72ch | Sans | Hierarchy | None |
| `technical` | `tech_book`, `code` | 78ch | Sans | Hierarchy | None |
| `dialogue` | `conversation`, `audio`, `video`, or `structure_type: chat` | 66ch | Sans | Speaker labels | Per section |
| `script` | `structure_type: script` | 66ch | Sans | Opener | None |
| `reference` | `kindle_clippings` | 66ch | Sans | Hierarchy | Per section |

`structure_type` overrides `content_type` only for `chat` and `script` — the two
layouts `content_type` cannot express. `book` and `paper` exist on both axes and
must not override, or a technical book laid out in numbered sections would lose
its 78ch measure to the prose profile.

An "opener" heading ignores `level`: a novel has one heading level and it marks
a pause, not a rank, so every chapter title gets the same air. "Hierarchy" sizes
by level so nesting stays visible.

Measure is set in `ch`, so it tracks each profile's own typeface rather than a
pixel width. Measured in the browser at 1400px: prose renders 64 characters per
line against the previous `max-w-3xl`, which ran to ~95. The research consensus
is 50–75 (66 ideal) and WCAG caps Latin text at 80; every profile's measure is
asserted inside that band by `readingProfile.test.ts`.

The profile picks the default. A reader preference overrides it.

## Reader preferences

`useReaderPreferences` stores typeface, text size, line spacing, line width and
background under `luminary-reader-prefs`; `resolveReadingLayout()` folds them
over the profile's defaults.

`"auto"` and a null measure mean "whatever the profile chose" and are the
defaults, so an untouched preference keeps tracking the profile instead of
freezing today's values into storage. Line width is clamped to 45–80
characters.

Text size reaches the text as `--reader-size` on the reading column, and is
handed to `MarkdownRenderer` as `text-[length:var(--reader-size)]` rather than
inherited: Tailwind's `prose` sets an absolute `font-size`, so inheritance left
every paragraph at 16px however the slider moved. Line spacing travels the same
way via `--reader-leading`, because `prose` also sets its own paragraph
`line-height`.

## Speaker turns

`parseSpeakerTurns()` splits a transcript body on `Speaker: utterance` lines so
the dialogue profile can set each name as a label. It returns null for anything
that is not a transcript, and needs two matching lines before it will restyle a
section — one incidental `Note: ...` line must not turn a chapter into a
transcript.

A transcript's own header (`Transcript: ...`, `Date: ...`, `Participants: ...`)
has the exact shape of a turn and was rendered as three people who each spoke
once. Leading labels are demoted to plain text by **recurrence**, not by a list
of known header words, which keeps the rule working in any language: a real
speaker takes more than one turn, so a label occurring once before anybody has
spoken twice is metadata. The rule engages only once some speaker actually
recurs — in a short exchange where three people each speak once, every label is
a person.

Sections carrying highlights render as markdown instead: highlights are injected
as `<mark>` HTML, which the turn splitter would show as literal tags.

## Never invent a heading

See I-30 in `docs/invariants.md` for the rule and its enforcement.

`sectionTitle()` (`frontend/src/components/reader/sectionTitle.ts`) derives a
label from the first 64 characters of the body when the stored heading is
unusable — an anchor id like `_r9szt46p8rxa`, or a stray PDF glyph. That label
belongs to the contents panel, which needs an entry to navigate with. The
reading flow asks `hasAuthoredHeading()` instead and draws nothing when the
source gave no heading.

An empty `heading` is therefore meaningful: it records that the document had
none. Nothing downstream may fill it.

## Dialogue keeps utterances in the body

A transcript's matched line *is* the utterance, so `_segment` would store it as
a heading over an empty body. `_is_marker` sends any matched line that reads as
prose to the body instead, and chat always routes to `_segment_chat_grouped`
regardless of turn count — a short transcript groups into one section, which
reads correctly, where the generic loop stranded every turn.

The speaker stays a label inside the turn. Rendering speaker labels as anything
richer than body text is Phase 3.

## Phasing

| Phase | Change | State |
|---|---|---|
| 1 | `sections.body`; reader stops re-joining chunks | Done |
| 2 | `documents.structure_type`; dialogue segmentation; no invented headings | Done |
| 3 | Profile-driven rendering; speaker turns | Done |
| 4 | Reader preferences; auto-extending section window; capped preview payload | Done |

Phases 1 and 2 change what ingestion stores, so a document reads at full
fidelity only after re-upload. Phases 3 and 4 are render-time and apply
immediately.

## Section window

`listLimit` bounds how many sections are in the DOM and extends by 200 when its
tail scrolls into view. It replaced a "Load next 500 sections" button: the
window exists to bound the DOM, which is not the reader's problem, and a book
that stops until you press something is the thing this reader is meant not to
be.

Full virtualization was rejected. `LazySection` already defers markdown
rendering until a section is near the viewport, so the remaining cost of an
off-screen section is an empty div. Windowing with variable heights would have
to take over scroll-to-section, the active-section observer that drives the
contents panel, and highlight anchoring — for no measured gain.

## Preview payload

`sections.preview` is stored at up to 10,000 characters and `DocumentDetail`
carries one per section: opening DDIA sent 1.6 MB, 1.5 MB of it preview, for a
field the section list renders under `line-clamp-2`. `WIRE_PREVIEW_CHARS` caps
it at 1,200 on the wire — measured, DDIA fell from 1,627 KB to 292 KB.

The cap sits well above two lines because two other consumers read this field:
`PredictPanel` extracts the section's first fenced code block from it, and the
Feynman dialog falls back to it when no cached summary exists. Storage is
unchanged, so server-side readers (`routers/flashcards.py`) are unaffected.

## Rejected

**Docling / Unstructured for layout analysis.** Their element taxonomy (title,
section-header, paragraph, list, table, figure, caption, code, quote, formula)
is the right internal shape and Phase 3 profiles should target it. The models
themselves are gigabytes and the PDF path already extracts structure from font
size. Revisit only if PDF structure is the measured bottleneck after Phase 3.
