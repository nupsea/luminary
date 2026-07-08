---
description: Notes editor redesign -- implementation plan for agent execution. Branch feat/notes-redesign.
---

# Notes Redesign — Implementation Plan

Branch: `feat/notes-redesign` (off `master` @ bd19a2c). One work package (WP) per agent
session. Every WP ships independently: green gates, no half-wired UI.

## Why (from the 2026-07-08 UX review)

1. **P0 data loss**: no autosave; the edit Sheet discards on Esc/overlay click
   (`NoteReaderSheet.tsx` `onOpenChange` -> `onClose`).
2. **P0 mode split**: read vs edit modal state machine; double-click-to-edit is
   undiscoverable. Modern note apps are always-editable.
3. **P1 broken linking**: `LinkAutocomplete.tsx` has zero importers (its parent
   NoteEditorDialog was deleted); `[[id|text]]` renders as an inert span
   (`MarkdownRenderer.tsx` code component); `notesApi` link helpers unused.
   Backend is fully alive: `GET/POST/DELETE /notes/{id}/links` (returns
   `{outgoing, incoming}`), `GET /notes/autocomplete`, Kuzu note graph, typed
   edges (elaborates/contradicts/see-also/supports/questions).
4. **P1 hostile writing surface**: raw `<textarea>` -- no list continuation, no
   markdown keymaps, monospace input vs serif preview, fighting scroll sync.
5. **P2 metadata cockpit**: tags + collections + source docs + image-spec
   buttons + mermaid cheat sheet all stacked around the text area.
6. **P2 three editor implementations**: NoteEditor/MarkdownSplitEditor (notes +
   blog), and an unrelated inline `NoteEditor` in `reader/SectionListItem.tsx`.

## Locked decisions

- **Editor core = CodeMirror 6** (markdown language mode). NOT TipTap/Milkdown:
  WYSIWYG document models cannot round-trip our custom markdown (Excalidraw
  refs, `__LUMINARY_IMG__` paths, `[[id|text]]` markers, `|size` image alt
  pipes) without fidelity loss. CM6 keeps text as text.
- **Autosave** (debounced PATCH) replaces explicit Save as the primary
  mechanism. Ctrl+S stays as flush. New notes create a draft row on first
  meaningful input.
- **Single live editor**: read/edit mode split is removed. A "reading view"
  toggle (serif `MarkdownRenderer`, chrome-free) replaces read mode.
- **Notes become routable**: `/notes/:id` full page. The Sheet remains only as
  a quick-capture composer (reader + gap-analysis entry points).
- **Storage stays SQLite** (`NoteModel.content` markdown text). No .md file
  mirror in this feature; Obsidian zip export remains the portability path.
- Split-pane preview becomes **opt-in** (kept for mermaid/math-heavy
  authoring), not the default posture.

## Non-goals

- No WYSIWYG / rich-text document model.
- No on-disk .md vault mirror.
- No collaborative editing, no mobile layout work.
- No backend schema changes to `NoteModel` (all endpoints needed exist).
- Blog publishing flows keep working but get no redesign (they inherit the new
  editor via `MarkdownSplitEditor` compatibility only).

## Personas served (acceptance lens for every WP)

- **Quick jotter**: capture in <5s, zero required metadata, nothing lost.
- **Structured summarizer**: headings/tables/math, outline nav, source-doc grounding.
- **Visual learner**: mermaid + excalidraw + images, discoverable via slash menu.
- **Connector**: `[[` links, backlinks, tags -- currently unserved despite full backend.

---

## Work packages

### WP1 — Autosave + draft safety (P0, ship first)

Frontend only. Files: `frontend/src/components/NoteReaderSheet.tsx`,
`frontend/src/lib/noteEditorUtils.ts` (new hook), `frontend/src/lib/notesApi.ts`.

- New `useNoteAutosave(noteId, draft, {debounceMs: 1000})` hook:
  - Existing note: debounced `PATCH /notes/{id}` on content/title/tags change.
  - New note: first non-whitespace content creates the note (`POST /notes`),
    hook then flips to PATCH mode with the returned id. Collection staging
    logic in `saveMut` moves to post-create.
  - Exposes `status: "idle" | "saving" | "saved" | "error"` + `flush()`.
  - In-flight guard: never issue overlapping PATCHes; latest state wins
    (AbortController, same pattern as `ClipCard.handleNoteBlur`).
- Sheet dismissal: `onOpenChange(false)` calls `flush()` then closes. No
  discard path exists anymore. If a draft was created but content is empty at
  close, DELETE it -- **surface this in the UI as "Empty note discarded"
  toast** (delete-on-close of user-visible data must be announced).
- Save button becomes a status pill ("Saving... / Saved / Retry"). Ctrl+S
  (`useNoteSaveShortcut`) calls `flush()`.
- Error state (I-10): failed autosave shows inline retry, content is never
  dropped from local state.
- Cancel-edit revert behavior is removed with the button (WP3 removes the mode
  split; until then Cancel just closes after flush).

Tests: vitest for the hook (fake timers: debounce, create->patch flip, abort
on rapid typing, flush on unmount). Manual: type, kill the tab, reopen --
content persisted.

### WP2 — CodeMirror 6 editor core

Files: new `frontend/src/components/notes/MarkdownCodeEditor.tsx`, modify
`MarkdownSplitEditor.tsx`, `noteEditorUtils.ts`, `NoteEditor.tsx`.

- `npm i` (frontend/): `codemirror`, `@codemirror/lang-markdown`,
  `@codemirror/language-data`, `@lezer/highlight`. Verify bundle: `npm run
  build` and check chunk sizes; CM6 must be in the notes route chunk, not the
  entry chunk (dynamic import if needed).
- `MarkdownCodeEditor` props mirror the textarea contract:
  `{value, onChange, onPasteImage, placeholder, autoFocus, className}` plus an
  imperative ref `{insertAtCursor(md, blockMode), getSelection(), focus()}`.
- Feature set in this WP: markdown syntax highlighting (headings, bold,
  code fences visually distinct), list/quote/checkbox continuation on Enter,
  Mod-b/Mod-i toggles, history (undo depth), placeholder, paste-image via the
  existing `uploadNoteAsset` path (port `createImagePasteHandler`), theme
  matching Tailwind tokens (light + dark via `.dark` class observation).
- Port `insertAtTextareaCursor` semantics to a CM6 transaction helper --
  mermaid/excalidraw insertion and image-size markdown in `NoteEditor.tsx`
  switch to the imperative ref. Delete the textarea-position `setTimeout`
  hacks.
- `MarkdownSplitEditor` swaps its textarea pane for `MarkdownCodeEditor`.
  Scroll-sync: CM6 `scrollDOM` replaces the textarea in `syncScroll`. The
  `textareaRef` prop is replaced by the editor ref; update the two call sites
  (`NoteEditor.tsx`, blog dialogs) in the same WP -- no dual-mode flag left
  behind.
- Ctrl+S must reach the window handler (CM6 default keymap does not bind
  Mod-s; verify no preventDefault swallow).

Tests: vitest for transaction helpers (insert block at cursor, image markdown
replace-selection). Component test: type `- item` + Enter -> next bullet
appears. `tsc -b` and `npm run build` green. Blog edit + publish dialogs
manually verified (they share the component).

### WP3 — Collapse modes + properties rail

Files: `NoteReaderSheet.tsx` (major rewrite), `NoteEditor.tsx`.

- Delete the `mode` state machine: the sheet always shows the live editor.
  Title input always visible on top (placeholder "Untitled note").
- Add "Reading view" toggle (book icon, keyboard `Mod-e` to flip): renders
  `MarkdownRenderer serif` full-width, hides all editing chrome. Not
  persisted; defaults to editor.
- Metadata (tags + suggestions, collections, source docs) moves out of the
  main column into a collapsible right rail (or bottom drawer under a
  "Properties" disclosure at narrow width). Collapsed by default for new
  notes; remembers open state per session (Zustand, not localStorage).
- Split preview becomes a toolbar toggle (off by default) instead of the
  default layout. `layout="tabs"` callers unaffected.
- Delete: read-mode double-click handler, Edit/Cancel buttons, `focusMode`
  width juggling (editor width is now constant 90vw; reading view 58vw
  equivalent via max-width on the prose column).
- Keep: delete-with-confirm, concept chips, tag navigate, source-doc
  back-link.

Tests: vitest smoke of sheet render states (loading skeleton, empty content
placeholder, error -- I-10). Manual persona pass: jot a 3-line note start to
finish counting clicks (target: open, type, close -- zero required fields).

### WP4 — Links end-to-end (highest learning value)

Files: new `frontend/src/components/notes/NoteLinkAutocomplete.tsx` (CM6
widget), `MarkdownCodeEditor.tsx`, `MarkdownRenderer.tsx`, new
`NoteBacklinks.tsx`, `NoteReaderSheet.tsx`; reuse `notesApi.ts` link helpers
(`fetchNoteLinks`, `createNoteLink`, `deleteNoteLink` -- currently dead).

- CM6 autocomplete source triggered by `[[`: queries
  `GET /notes/autocomplete?q=`, renders title + snippet, insert produces
  `[[id|title]]` and fires `POST /notes/{id}/links` with the chosen link type
  (segmented control in the popup, default `see-also` -- port the interaction
  design from the orphaned `LinkAutocomplete.tsx`, then delete that file).
  Link creation only fires when the source note has an id (autosave draft
  guarantees one after WP1).
- `MarkdownRenderer.tsx`: the `[note:id|label]` span becomes a button that
  navigates to the note (within Notes context: open that note; the renderer
  gets an optional `onNoteLinkClick(id)` prop; absent prop = current inert
  behavior so chat/blog surfaces are unchanged).
- `NoteBacklinks` section at the bottom of the note view: `GET
  /notes/{id}/links`, two groups (Linked from this note / Mentioned in),
  link-type badge, click navigates. Loading skeleton + empty state "No links
  yet -- type [[ to connect notes" (I-10).
- Deleting a link from the backlinks list = `DELETE
  /notes/{id}/links/{target}` with inline confirm (data delete -> confirm).

Tests: vitest for the `[[` trigger detection + marker insertion. Backend is
untouched but add one pytest only if a contract gap is found (e.g. autocomplete
excluding the current note -- verify, don't assume). Manual: create A->B link,
open B, see A in backlinks, navigate both ways.

### WP5 — Slash menu + insert UX

Files: `MarkdownCodeEditor.tsx`, new `SlashMenu` extension file,
`NoteEditor.tsx`, `MermaidQuickInsert.tsx` + `MermaidCheatSheet.tsx` (retire),
`MarkdownRenderer.tsx` (image popover).

- `/` at line start opens a command menu: Heading 1-3, Bullet/Numbered/Todo
  list, Table, Code block, Math block, Divider, Image, Mermaid (submenu with
  the `MermaidQuickInsert` templates + "cheat sheet" help entry), Excalidraw
  (opens `NoteDiagramDialog`), Link to note (enters `[[` flow).
- Retire the `NoteEditor` toolbar: image-size buttons replaced by a popover on
  click of a rendered image in preview/reading view (Small/Medium/Large writes
  the `|size` alt pipe back into the markdown); `MermaidCheatSheet` and
  `MermaidQuickInsert` fold into the slash menu; delete `showToolbar`,
  `showImageSize` props and the toolbarOpen state.
- Keyboard: full navigation (arrows + Enter + Esc) in the menu; menu must not
  trap focus on Esc.

Tests: vitest for slash trigger (line start only, not mid-word), menu
filtering. Manual: insert each block type, verify preview renders it.

### WP6 — `/notes/:id` route + capture unification

Files: `App.tsx` (route), new `frontend/src/pages/Notes/NotePage.tsx`,
`Notes.tsx`, `reader/SectionListItem.tsx`, `reader/DocumentReader.tsx`, new
shared `QuickNoteComposer.tsx`.

- `NotePage`: full-page note editor (same building blocks as the sheet --
  title, `MarkdownCodeEditor`, properties rail, backlinks). Outline rail on
  the left for notes with >=3 headings (parsed client-side, click scrolls).
  Deep-linkable; card/list click in `Notes.tsx` navigates here instead of
  opening the sheet. Back button via `useBackNavigation`.
- Cross-tab entry points keep working: `luminary:navigate` events and store
  preloads (`notePreload`) route to the page or composer as appropriate
  (I-11: no URL hacks for cross-tab).
- `QuickNoteComposer`: minimal capture surface (title optional, body,
  autosave, "open full note" escape hatch). Replaces (a) the Sheet's isNew
  mode incl. the header append-picker (append becomes a composer command
  "Append to existing..." reusing the same picker logic), (b) the bespoke
  inline `NoteEditor` in `SectionListItem.tsx` (delete it), keeping
  section_id/document_id wiring.
- `NoteReaderSheet` shrinks to: composer host for reader/gap-analysis
  contexts. If nothing else remains of it, delete and rename accordingly.

Tests: vitest route smoke (loads note by id, 404 state for bad id -- I-10).
Manual: reader -> take note on section -> appears in /notes with section
back-link; gap-detect "Take a note" preload still works.

### WP7 — Cleanup + consistency

Files: `Notes.tsx`, `App.tsx`, backend untouched (legacy params stay for API
compat).

- Remove the `group` FilterState branch + header case (no UI sets it; backend
  `group` param stays).
- List view title column uses `note.title ?? deriveTitle(content)` (same rule
  as cards); keep `stripMarkdown` for the preview cell (I-12).
- Delete dead code: `LinkAutocomplete.tsx` (superseded in WP4),
  `MermaidQuickInsert`/`MermaidCheatSheet` files (folded into slash menu in
  WP5), unused props on `NoteEditor`/`MarkdownSplitEditor`, the second
  `NoteEditor` in SectionListItem (WP6 did it; verify no strays with a grep).
- `docs/architecture.md` Notes tab description updated; CHANGELOG entry.
- Full `make ci` + `npm run build` (public tier: `VITE_SURFACE_TIER=public
  npm run build` must not pull CM6 into stripped surfaces' chunks).

---

## Agent execution protocol

1. One WP per session, in order. WP2 must precede 3/4/5. WP1 is independent
   and first. WP6 needs 2-5. WP7 last.
2. Read before writing: every file listed in the WP + `docs/invariants.md` +
   `.claude/rules/common/efficiency.md`. Read `Notes.tsx` sections by line
   range, not whole-file.
3. Code style: no docstrings/WHAT comments -- only non-obvious WHY
   (established feedback rule). Match surrounding idiom (Tailwind tokens,
   TanStack Query patterns, Zustand store slices).
4. Quality gates in order (I-13): `cd frontend && npx eslint src --max-warnings 0`
   -> `npx vitest run` -> `npx tsc -b` -> `npm run build`. Backend-touching WPs
   add `cd backend && uv run ruff check . && uv run pytest` (uv only, I-15).
5. Every new UI surface has loading / error / empty states (I-10).
6. No new external network dependencies (I-16); CM6 is a bundled npm package,
   no CDN imports.
7. Update the checklist below in this file at WP completion; note deviations
   inline. Commits: one per WP, `feat(notes): <wp summary>`, only when the
   user signs off.

## Progress

- [x] WP1 autosave + draft safety — done 2026-07-08. Deviations from the WP1
  text: (a) latest-wins is a serialized promise chain in
  `lib/noteAutosave.ts`, not an AbortController — a create can never race the
  patch behind it and no API signatures changed; (b) the hook lives in a new
  `lib/noteAutosave.ts` with a framework-free `createNoteAutosaver` core
  (injectable create/patch) so it unit-tests under the node vitest env (no
  testing-library in this repo); (c) empty content is never persisted --
  no draft row until real content, and an existing note keeps its last saved
  body (matches the old disabled-Save behavior); the close path deletes an
  auto-created draft that ended empty, with an "Empty note discarded" toast;
  (d) autosave is suspended while an append target is picked -- append rewrites
  another note's content, so it stays an explicit button (bindKey null);
  (e) the non-append edit footer is now status pill + Done (Cancel had nothing
  left to cancel). 10 new tests in `noteAutosave.test.ts`; lint/tsc/build
  green; pre-existing pdfHighlightOverlay/pdfTocUtils failures confirmed on
  HEAD before this change.
- [x] WP2 CodeMirror 6 editor core — done 2026-07-08. `MarkdownCodeEditor.tsx`
  (CM6 view, markdown lang + language-data fences, list/quote/task
  continuation, Mod-b/Mod-i, history, placeholder, shadcn-token theme so dark
  mode flips via CSS vars, paste-image via `onPasteImage`, imperative handle
  insertBlock/insertInline/replaceSelection/getSelection/scrollDOM). Pure
  transaction specs in `markdownEditorCommands.ts` (14 headless tests incl.
  real CM continuation commands on EditorState -- no DOM needed).
  `MarkdownSplitEditor` swapped textarea -> CM6; props renamed
  (`textareaRef`->`editorRef`, `onPaste`->`onPasteImage`,
  `textareaClassName`->`editorClassName`); all 3 call sites updated same WP
  (NoteEditor, BlogEditDialog, BlogPublishDialog). Dead textarea helpers
  (`insertAtTextareaCursor`, `createImagePasteHandler`) deleted from
  noteEditorUtils. Bundle: CM6 landed in a lazy shared chunk (~572K raw);
  entry chunk unchanged at 1.2M. Live-drive verified via Playwright+Chrome:
  CM editor mounts in the sheet, `- item`+Enter continues the list, Mod-b
  wraps, autosave create->flush->persist works, read-mode renders; syntax
  highlighting confirmed by screenshot. Known quirk: CM's default Escape
  binding (simplifySelection) can consume the first Esc when a range
  selection is active; second Esc closes the sheet.
- [x] WP3 collapse modes + properties rail — done 2026-07-08. NoteReaderSheet
  rewritten: no read/edit mode machine, always-live editor at constant 90vw;
  header icon cluster = reading-view toggle (Mod-e, prose max-w-3xl), split
  preview toggle (off by default; `MarkdownSplitEditor` gained an
  `"editor"`-only layout), properties-rail toggle. Rail (320px, right)
  holds tags + suggestions + concept chips + collections + source docs;
  state lives in a new NON-persisted zustand store `store/noteEditorUi.ts`
  (session-scoped per spec). `NoteEditor` slimmed to editor+toolbar only
  (meta props deleted -- the sheet owns metadata now). focusMode and
  double-click-to-edit deleted; Done button = flush+close (handleDone merged
  into handleSheetDismiss). Deviations: (a) auto tag-suggest no longer
  auto-ADDS tags (old edit-mode autoAdd) -- suggestions always render as
  opt-in chips; (b) no sheet render-state vitest (node env, no
  testing-library) -- I-10 states covered by the live drive instead.
- [x] WP4 links end-to-end + backlinks — done 2026-07-08.
  `noteLinkCompletion.ts` ([[ trigger via CompletionContext.matchBefore,
  server-filtered, excludes current note, marker-safe labels) wired into
  MarkdownCodeEditor via `autocompletion({override})`; config threaded
  NoteEditor->MarkdownSplitEditor->MarkdownCodeEditor and supplied by the
  sheet (fetch=/notes/autocomplete, onPick=POST /links). `NoteBacklinks.tsx`
  (outgoing+incoming from GET /notes/{id}/links, type badge, inline-confirm
  remove, loading/empty states) rendered in edit + reading views.
  MarkdownRenderer `[[id|text]]` spans become navigable buttons when
  `onNoteLinkClick` is set; sheet flushes pending edits before swapping notes
  (handleOpenLinkedNote) so link navigation can't drop a draft. Notes.tsx
  implements `onOpenNote` via new `getNote`. 9 headless tests
  (noteLinkCompletion.test.ts). Deviations: (a) link-type segmented control
  NOT ported into the completion popup (CM popups don't host interactive
  controls well) -- links create as `see-also`; type is visible in the
  backlinks panel and re-typing means remove+relink (full type picker can
  ride WP5/WP6); (b) old orphaned `LinkAutocomplete.tsx` left for WP7
  deletion. Live-drive verified: popup on [[, Enter inserts marker + POST
  /links (see-also), backlinks panel on both sides, B->A navigation via
  backlink row and A shows incoming from B. Note: Enter-accept needs the
  async fetch to settle; sub-100ms scripted keystrokes can outrun it (humans
  won't).
- [x] WP5 slash menu + insert UX — done 2026-07-08. `slashCommands.ts`: `/` at
  line start (mid-word never triggers) opens a CM completion menu with
  sections Blocks/Lists/Insert/Diagrams -- H1-3, bullet/numbered/task list,
  quote, divider, table, code block (cursor inside fence), math block, image,
  "Link to note" (inserts [[ and chains into the note autocomplete), 4
  mermaid templates (template source shown in the completion info panel --
  this replaces the cheat sheet), and Draw diagram (Excalidraw). NoteEditor
  toolbar fully retired: image-spec buttons, MermaidQuickInsert +
  MermaidCheatSheet components and MERMAID_CHEAT_SHEET constant deleted;
  image sizing is now a click-popover on rendered images
  (MarkdownRenderer.onSetImageSize + pure `setImageSizeInMarkdown` that maps
  mirrored /images/local/ URLs back to __LUMINARY_IMG__) wired in the split
  preview and reading view. 12 new headless tests (trigger position,
  filtering, apply outputs via state-backed view stub, image-size rewrite
  incl. URL mapping). Live-drive verified: menu on /, /tab -> table inserted,
  /mer -> mermaid inserted and SVG renders in preview, old toolbar gone.
  Also (user feedback, same session): properties rail now uses full height --
  tags capped at 30% with scroll, Collections and Source Documents split the
  remaining space (flex-1 lists) instead of max-h-40/32 boxes.
  Post-WP5 polish (user feedback): (a) completion popup rethemed to the app's
  popover tokens (--popover/--accent/--font-sans, styled sections/details/
  info panel) replacing CM's stark blue default; (b) popup latency cut --
  `activateOnTypingDelay: 25` and `interactionDelay: 30` (the 75ms default
  interaction guard was rejecting prompt ArrowDown/Enter, which fell through
  to cursor motion and killed the popup -- root cause of the WP4 Enter
  flake); (c) single editable title: the sheet header IS the title input
  (SheetTitle kept sr-only for a11y), body title input removed; (d) Escape
  layering fixed -- Radix grabs Escape at document capture before CM, so
  MarkdownCodeEditor now closes an open completion via a window-capture
  keydown handler (preventDefault+stopPropagation) and the sheet keeps a
  backup onEscapeKeyDown guard; Esc with popup open closes only the popup.
- [ ] WP6 /notes/:id route + capture unification
- [ ] WP7 cleanup + consistency + full CI

## Risks

- **CM6 bundle weight**: keep it lazy-loaded with the notes chunk; check
  `npm run build` output per WP2/WP7.
- **Scroll-sync regression** when swapping textarea -> CM6 scrollDOM: if it
  fights, drop sync for the opt-in split view rather than shipping jank.
- **Autosave vs slow LLM side-effects**: PATCH triggers background
  title/description/embedding work server-side per save; debounce >=1s and
  content-hash short-circuit already exist server-side -- verify no request
  storm in the network tab while typing (WP1 acceptance item).
- **Sheet focus management vs CM6**: Radix Sheet traps focus; confirm CM6
  popups (autocomplete, slash menu) render inside the trap (portal into the
  sheet content, not document.body) in WP4/WP5.
